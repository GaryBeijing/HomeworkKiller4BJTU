# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-11 20:00
# 文件名: browser_login.py
# 主要用途: 通过可见 Edge + CDP 完成 icourse163 登录；失效窗口清理、临时配置目录重试、超时关闭与无 Origin 的 CDP 连接。
# 文件版本: 4.4.3
"""通过真实浏览器完成 icourse163 登录。

流程与人工登录一致：打开首页 → 点击「登录/注册」→ 切到「邮箱登录」
→ 在 URS iframe 中填写邮箱、密码并提交。加密、指纹和风控全部由浏览器完成。
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

from requests.cookies import RequestsCookieJar, create_cookie

from .config import LOGIN_PAGE, browser_port_file, browser_profile_dir
from .browser import TARGET_DOMAIN

__version__ = "4.4.3"
# 端口文件超过该时长视为上一次失败留下的旧窗口。
_PORT_FILE_TTL_SECONDS: int = 15 * 60
# CDP 启动等待上限（秒）。
_CDP_START_TIMEOUT: int = 20

Log = Callable[[str], None]


class BrowserLoginError(Exception):
    """浏览器登录失败。"""


# 登录弹窗可能有多个标签；按账号类型优先尝试。
LOGIN_TABS = {
    # 爱课堂/爱课程账号（含手机号注册的账号）：只走「爱课程登录」。
    "aiketang": ("爱课程登录", "账号登录"),
    "icourse": ("爱课程登录", "账号登录"),
    "phone": ("爱课程登录", "账号登录"),
    # 网易通行证：邮箱 / 手机号分别走 URS。
    "netease": ("邮箱登录",),
    "netease_phone": ("手机号登录", "手机验证码登录"),
    "auto": ("爱课程登录", "邮箱登录", "手机号登录"),
}

ACCOUNT_INPUT_SELECTORS = (
    "input[name=email]",
    "input[name=phone]",
    "input[name=mobile]",
    "input[name=username]",
    "input[name=account]",
    "input[type=tel]",
)


def member_from_cookies(jar: RequestsCookieJar) -> dict[str, Any]:
    """从 STUDY_INFO Cookie 解析用户，避免登录后调用 getMocMember 破坏 SPOC 上下文。

    STUDY_INFO 形如 ``email|loginType|uid|timestamp``。
    """
    raw = None
    for cookie in jar:
        if cookie.name == "STUDY_INFO":
            raw = cookie.value
            break
    if not raw:
        return {}
    parts = str(raw).strip().strip('"').split("|")
    if len(parts) < 3:
        return {}
    email = parts[0].strip()
    uid = None
    try:
        uid = int(parts[2])
    except (TypeError, ValueError):
        uid = None
    member: dict[str, Any] = {}
    if uid:
        member["id"] = uid
    if email:
        member["loginId"] = email
        member["email"] = email
    return member


def needs_spoc_warmup(jar: RequestsCookieJar) -> bool:
    return not any(cookie.name.startswith("l_yd_s_") for cookie in jar)


def has_cookie(jar: RequestsCookieJar, name: str) -> bool:
    """同名多域 Cookie 时不能用 jar.get(name)，会抛 CookieConflictError。"""
    return any(cookie.name == name for cookie in jar)


# --------------------------------------------------------------------- 浏览器
def _exe_candidates(browser: str) -> list[Path]:
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        program_files = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        ]
        table = {
            "edge": [p / "Microsoft/Edge/Application/msedge.exe" for p in program_files],
            "chrome": [p / "Google/Chrome/Application/chrome.exe" for p in program_files]
            + [local / "Google/Chrome/Application/chrome.exe"],
            "brave": [p / "BraveSoftware/Brave-Browser/Application/brave.exe" for p in program_files]
            + [local / "BraveSoftware/Brave-Browser/Application/brave.exe"],
        }
    elif sys.platform == "darwin":
        table = {
            "edge": [Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")],
            "chrome": [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")],
            "brave": [Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")],
        }
    else:
        table = {
            "edge": [Path("/usr/bin/microsoft-edge"), Path("/usr/bin/microsoft-edge-stable")],
            "chrome": [Path("/usr/bin/google-chrome"), Path("/usr/bin/google-chrome-stable")],
            "brave": [Path("/usr/bin/brave-browser")],
        }

    if browser in ("", "auto"):
        order = ("edge", "chrome", "brave")
    else:
        order = (browser,)
    candidates: list[Path] = []
    for key in order:
        candidates.extend(table.get(key, []))
    return candidates


def find_browser_executable(browser: str = "auto") -> Path:
    for candidate in _exe_candidates(browser):
        if candidate.is_file():
            return candidate
    raise BrowserLoginError(
        f"没有找到 {browser} 浏览器，请安装 Edge/Chrome，或手动导入 Cookie。"
    )


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _cdp_version(port: int) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version", timeout=1.5
        ) as response:
            return json.load(response)
    except Exception:
        return None


class CDP:
    """极简 Chrome DevTools Protocol 客户端。"""

    def __init__(self, ws_url: str) -> None:
        import websocket

        # Chrome/Edge 111+ 的 DevTools 端点会拒绝带 Origin 的 WebSocket；
        # websocket-client 默认会发送 http://host:port，导致窗口登录 403。
        self.ws = websocket.create_connection(
            ws_url, timeout=30, suppress_origin=True
        )
        self._id = 0

    def call(self, method: str, params: dict | None = None, session: str | None = None) -> dict:
        self._id += 1
        message: dict[str, Any] = {"id": self._id, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        self.ws.send(json.dumps(message))
        while True:
            try:
                data = json.loads(self.ws.recv())
            except Exception as exc:
                raise BrowserLoginError("浏览器调试连接已断开（窗口被关闭）。") from exc
            if data.get("id") != self._id:
                continue
            if "error" in data:
                raise BrowserLoginError(
                    f"浏览器操作失败：{data['error'].get('message', data['error'])}"
                )
            return data.get("result", {})

    def close(self) -> None:
        """关闭整个浏览器。"""
        try:
            self.call("Browser.close")
        except Exception:
            pass
        self.disconnect()

    def disconnect(self) -> None:
        """只断开调试连接，保留浏览器进程（复用时使用）。"""
        try:
            self.ws.close()
        except Exception:
            pass


# --------------------------------------------------------------------- 会话
class BrowserLogin:
    def __init__(
        self,
        browser: str = "auto",
        log: Log | None = None,
        headless: bool = False,
        start_url: str | None = None,
    ) -> None:
        self.browser = browser or "auto"
        self.log = log or (lambda message: None)
        self.headless = headless
        self.start_url = start_url
        self.proc: subprocess.Popen | None = None
        self.port: int | None = None
        self.cdp: CDP | None = None
        self.reused = False
        # 重试时使用的临时配置目录；关闭窗口后删除。
        self._temp_profile: Path | None = None

    # ------------------------------------------------------------- 启动/复用
    def _discard_port_file(self) -> None:
        """删除旧的调试端口文件。"""
        try:
            browser_port_file().unlink()
        except OSError:
            pass

    def _reuse_existing(self) -> bool:
        """复用本程序上一次打开的登录窗口。

        只有端口文件未过期、CDP 可连接且窗口中存在慕课页面时才复用；
        否则关闭旧窗口并重新启动，避免失效窗口导致登录一直等到超时。
        """
        path: Path = browser_port_file()
        try:
            if time.time() - path.stat().st_mtime > _PORT_FILE_TTL_SECONDS:
                self._discard_port_file()
                return False
            port = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return False
        version = _cdp_version(port)
        if not version:
            self._discard_port_file()
            return False
        try:
            cdp = CDP(version["webSocketDebuggerUrl"])
        except Exception:
            self._discard_port_file()
            return False
        try:
            targets = cdp.call("Target.getTargets").get("targetInfos", [])
            usable = any(
                item.get("type") == "page"
                and "icourse163" in str(item.get("url") or "")
                for item in targets
            )
        except Exception:
            usable = False
        if not usable:
            self.log("检测到失效的旧登录窗口，正在关闭并重新启动…")
            try:
                cdp.call("Browser.close")
            except Exception:
                pass
            try:
                cdp.disconnect()
            except Exception:
                pass
            self._discard_port_file()
            return False
        self.cdp = cdp
        self.port = port
        self.reused = True
        self.log(f"复用已打开的浏览器窗口（端口 {port}）")
        return True

    def _cleanup_failed_process(self) -> None:
        """终止启动失败的浏览器进程并清理端口文件。"""
        if self.proc is not None:
            try:
                if self.proc.poll() is None:
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
            except Exception:
                pass
            self.proc = None
        self._discard_port_file()

    def _launch_with_profile(self, profile: Path, temporary: bool) -> None:
        """使用指定配置目录启动浏览器并连接 CDP。"""
        exe = find_browser_executable(self.browser)
        profile.mkdir(parents=True, exist_ok=True)
        port = _free_port()
        mode = "后台" if self.headless else ""
        self.log(f"正在启动 {exe.name} 登录{mode}窗口…")
        args = [
            str(exe),
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if temporary:
            args.append("--disable-extensions")
        if self.headless:
            args += [
                "--headless=new",
                "--disable-gpu",
                "--window-size=1280,900",
                "--lang=zh-CN",
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/156.0.0.0 Safari/537.36 Edg/156.0.0.0",
            ]
        else:
            args.append("--new-window")
        args.append(self.start_url or "https://www.icourse163.org/")
        self.proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        version = None
        deadline: float = time.time() + _CDP_START_TIMEOUT
        while time.time() < deadline:
            time.sleep(0.5)
            if self.proc.poll() is not None:
                self.proc = None
                self._discard_port_file()
                raise BrowserLoginError(
                    "浏览器启动后立即退出。可能已存在使用同一配置目录的窗口。"
                )
            version = _cdp_version(port)
            if version:
                break
        if not version:
            self._cleanup_failed_process()
            raise BrowserLoginError("无法连接到浏览器调试端口，请重试。")

        browser_port_file().parent.mkdir(parents=True, exist_ok=True)
        browser_port_file().write_text(str(port), encoding="utf-8")
        self.port = port
        self.cdp = CDP(version["webSocketDebuggerUrl"])

    def launch(self) -> None:
        """启动或复用可见登录窗口；常规配置失败时用临时目录重试。"""
        if self._reuse_existing():
            return

        try:
            self._launch_with_profile(browser_profile_dir(), temporary=False)
            return
        except BrowserLoginError as exc:
            self._cleanup_failed_process()
            self.log(
                "常规登录窗口启动失败（%s），改用临时配置目录重试…" % exc
            )
        # 独立临时配置目录不会与用户已打开的浏览器争用 profile 锁。
        profile: Path = browser_profile_dir().parent / (
            "edge-profile-%d-%d" % (os.getpid(), int(time.time()))
        )
        self._temp_profile = profile
        self._launch_with_profile(profile, temporary=True)

    # ------------------------------------------------------------- 页面操作
    def _page_session(self) -> str:
        assert self.cdp
        targets = self.cdp.call("Target.getTargets").get("targetInfos", [])
        pages = [t for t in targets if t.get("type") == "page" and "icourse163" in t.get("url", "")]
        if not pages:
            created = self.cdp.call(
                "Target.createTarget", {"url": "https://www.icourse163.org/"}
            )
            time.sleep(2)
            targets = self.cdp.call("Target.getTargets").get("targetInfos", [])
            pages = [t for t in targets if t.get("targetId") == created.get("targetId")]
        if not pages:
            raise BrowserLoginError("浏览器中没有找到 icourse163 页面。")
        page = pages[0]
        session = self.cdp.call(
            "Target.attachToTarget", {"targetId": page["targetId"], "flatten": True}
        )["sessionId"]
        self.cdp.call("Page.enable", session=session)
        self.cdp.call("Runtime.enable", session=session)
        return session

    def _eval(self, expression: str, session: str, context: int | None = None) -> Any:
        assert self.cdp
        params: dict[str, Any] = {"expression": expression, "returnByValue": True}
        if context is not None:
            params["contextId"] = context
        result = self.cdp.call("Runtime.evaluate", params, session=session)
        return result.get("result", {}).get("value")

    def open_login_dialog(
        self, session: str, wait: float = 20, account_kind: str = "auto"
    ) -> None:
        click_js = (
            "(() => {"
            " const els=[...document.querySelectorAll('div,span,a,button')]"
            "   .filter(e=>e.children.length===0);"
            " const t=els.find(e=>/登录\\s*\\/\\s*注册|登录\\s*\\|\\s*注册/.test((e.textContent||'').trim()));"
            " if(t){t.click();return 'clicked';}"
            " return 'notfound';"
            "})()"
        )
        # member/login.htm 本身已经展示登录标签，不要再点首页的「登录/注册」。
        skip_click = bool(
            self.start_url and "member/login.htm" in self.start_url
        )
        clicked = False
        if not skip_click:
            deadline = time.time() + wait
            while time.time() < deadline:
                if self._eval(click_js, session) == "clicked":
                    clicked = True
                    break
                time.sleep(0.8)
            if not clicked:
                self.log("未找到「登录/注册」按钮，按当前登录页继续。")

        tabs = LOGIN_TABS.get(account_kind, LOGIN_TABS["auto"])
        for tab in tabs:
            tab_js = (
                "(() => {"
                f" const target={json.dumps(tab)};"
                " const els=[...document.querySelectorAll('*')].filter(e=>e.children.length===0);"
                " const exact=els.find(e=>(e.textContent||'').trim()===target);"
                " const fuzzy=els.find(e=>(e.textContent||'').trim().includes(target));"
                " const t=exact||fuzzy;"
                " if(t){t.click();return 'clicked';}"
                " return 'notfound';"
                "})()"
            )
            deadline = time.time() + max(3.0, wait / 3)
            while time.time() < deadline:
                if self._eval(tab_js, session) == "clicked":
                    self.log(f"已选择登录标签：{tab}")
                    time.sleep(0.5)
                    return
                time.sleep(0.6)
        self.log("没有识别到明确的登录标签，将尝试直接填写当前表单。")

    def _frames(self, session: str) -> list[str]:
        assert self.cdp
        tree = self.cdp.call("Page.getFrameTree", session=session)["frameTree"]
        out: list[str] = []

        def walk(node: dict) -> None:
            frame = node.get("frame", {})
            if "index_dl2_new" in frame.get("url", ""):
                out.append(frame.get("id", ""))
            for child in node.get("childFrames") or []:
                walk(child)

        walk(tree)
        return [f for f in out if f]

    def _login_context(
        self, session: str, wait: float = 20, account_kind: str = "auto"
    ) -> int | None:
        assert self.cdp
        main_probe = (
            "(() => {"
            " const sel='input[name=email],input[name=phone],input[name=mobile],"
            "input[name=username],input[name=account],input[type=tel],"
            "input.ux-input[type=text]';"
            " const accounts=[...document.querySelectorAll(sel)]"
            "   .filter(e=>e.offsetParent!==null && e.type!=='hidden');"
            " const pwds=[...document.querySelectorAll('input[type=password]')]"
            "   .filter(e=>e.offsetParent!==null);"
            " return !!(accounts.length && pwds.length);"
            "})()"
        )
        # URS 有两个 iframe：手机号用 input[name=email][type=tel]，
        # 邮箱用 input[name=email][type=text]；必须按账号类型选对。
        email_frame_probe = (
            "(() => {"
            " const email=document.querySelector('input[name=email][type=text]');"
            " const pwd=document.querySelector('input[name=password][type=password]');"
            " return !!(email && pwd && email.offsetParent!==null"
            "   && pwd.offsetParent!==null);"
            "})()"
        )
        phone_frame_probe = (
            "(() => {"
            " const phone=document.querySelector('input[name=email][type=tel]');"
            " const pwd=document.querySelector('input[name=password][type=password]')"
            "   || document.querySelector('input[name=email][type=password]');"
            " return !!(phone && pwd && phone.offsetParent!==null"
            "   && pwd.offsetParent!==null);"
            "})()"
        )

        def find_frame(probe: str) -> int | None:
            for frame_id in self._frames(session):
                try:
                    ctx = self.cdp.call(
                        "Page.createIsolatedWorld",
                        {"frameId": frame_id, "worldName": "moocok"},
                        session=session,
                    )["executionContextId"]
                except BrowserLoginError:
                    continue
                if self._eval(probe, session, ctx):
                    return ctx
            return None

        deadline = time.time() + wait
        while time.time() < deadline:
            if account_kind in ("aiketang", "icourse", "phone"):
                # 爱课堂/爱课程账号只在主页面表单登录，绝不走 URS 手机号。
                try:
                    if self._eval(main_probe, session):
                        return None
                except BrowserLoginError:
                    pass
            elif account_kind == "netease":
                ctx = find_frame(email_frame_probe)
                if ctx is not None:
                    return ctx
            elif account_kind == "netease_phone":
                ctx = find_frame(phone_frame_probe)
                if ctx is not None:
                    return ctx
            else:
                try:
                    if self._eval(main_probe, session):
                        return None
                except BrowserLoginError:
                    pass
                ctx = find_frame(email_frame_probe) or find_frame(phone_frame_probe)
                if ctx is not None:
                    return ctx
            time.sleep(0.6)
        raise BrowserLoginError("登录页/iframe 中没有找到账号和密码输入框。")

    def fill_and_submit(
        self, session: str, email: str, password: str, account_kind: str = "auto"
    ) -> None:
        ctx = self._login_context(session, account_kind=account_kind)
        fill_js = f"""
        (() => {{
          const accSel = 'input[name=email],input[name=phone],input[name=mobile],'
            + 'input[name=username],input[name=account],input[type=tel],'
            + 'input.ux-input[type=text]';
          const accounts = [...document.querySelectorAll(accSel)]
            .filter(el => el.offsetParent !== null && el.type !== 'hidden');
          const passwords = [...document.querySelectorAll('input[type=password]')]
            .filter(el => el.offsetParent !== null);
          if (!accounts.length || !passwords.length) return 'inputs-not-found';
          const account = accounts[0];
          const pwd = passwords[0];
          const set = (el, value) => {{
            const setter = Object.getOwnPropertyDescriptor(
              window.HTMLInputElement.prototype, 'value').set;
            setter.call(el, value);
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            el.dispatchEvent(new KeyboardEvent('keydown', {{bubbles: true, key: 'a'}}));
            el.dispatchEvent(new KeyboardEvent('keyup', {{bubbles: true, key: 'a'}}));
          }};
          account.focus();
          set(account, {json.dumps(email)});
          pwd.focus();
          set(pwd, {json.dumps(password)});
          pwd.blur();
          account.blur();
          const btn = document.querySelector(
            'a.u-loginbtn, button[type=submit], .u-loginbtn, .loginbtn, .j-submit, '
            + 'button.submit-button, .ux-btn.submit-button, button.ux-btn'
          );
          return btn ? (btn.className || btn.textContent || 'button') : 'no-button';
        }})()
        """
        state = None
        deadline = time.time() + 15
        while time.time() < deadline:
            state = self._eval(fill_js, session, ctx)
            if state != "inputs-not-found":
                break
            time.sleep(0.6)
            try:
                ctx = self._login_context(
                    session, wait=2, account_kind=account_kind
                )
            except BrowserLoginError:
                pass
        if state == "inputs-not-found":
            raise BrowserLoginError("登录 iframe 中的输入框不可用。")
        time.sleep(0.8)

        click_js = (
            "(() => {"
            " const b=document.querySelector("
            "'a.u-loginbtn, button[type=submit], .u-loginbtn, .loginbtn, .j-submit, "
            "button.submit-button, .ux-btn.submit-button, button.ux-btn');"
            " if(!b) return 'no-button';"
            " b.click(); return b.className || b.textContent || 'button';"
            "})()"
        )
        self._eval(click_js, session, ctx)
        self.log("已填写账号和密码并点击登录，等待结果…")

    def read_iframe_text(self, session: str) -> str:
        for frame_id in self._frames(session):
            try:
                ctx = self.cdp.call(
                    "Page.createIsolatedWorld",
                    {"frameId": frame_id, "worldName": "moocok-read"},
                    session=session,
                )["executionContextId"]
                text = self._eval(
                    "document.body ? document.body.innerText : ''", session, ctx
                )
            except BrowserLoginError:
                continue
            if text:
                return str(text)
        return ""

    def warm_up_spoc(self, session: str, page: str, wait: float = 5.0) -> None:
        """访问 SPOC 首页，让服务端下发 l_yd_s/ntes_zc_yd 等学校云 Cookie。"""
        assert self.cdp
        try:
            self.cdp.call(
                "Page.navigate",
                {
                    "url": (
                        "https://www.icourse163.org/home.htm"
                        "#/home/spocCourse"
                    )
                },
                session=page,
            )
            time.sleep(wait)
        except BrowserLoginError:
            pass

    # ------------------------------------------------------------- Cookie
    def cookies(self) -> RequestsCookieJar:
        assert self.cdp
        result = self.cdp.call("Storage.getCookies")
        jar = RequestsCookieJar()
        for item in result.get("cookies", []):
            domain = item.get("domain", "")
            if not domain.lower().lstrip(".").endswith(TARGET_DOMAIN):
                continue
            expires = item.get("expires")
            jar.set_cookie(
                create_cookie(
                    name=item.get("name", ""),
                    value=item.get("value", ""),
                    domain=domain,
                    path=item.get("path") or "/",
                    secure=bool(item.get("secure")),
                    expires=None if not expires or expires < 0 else int(expires),
                )
            )
        return jar

    def close(self) -> None:
        if self.cdp:
            if self.reused:
                # 复用外部启动的调试窗口：只断开连接，不要关掉浏览器，
                # 也不要删除 port 文件，否则 MCP / 下次命令会失去会话。
                self.cdp.disconnect()
            else:
                self.cdp.close()
            self.cdp = None
        if not self.reused:
            try:
                browser_port_file().unlink()
            except OSError:
                pass
        if self.proc:
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
            self.proc = None
        if self._temp_profile is not None:
            shutil.rmtree(self._temp_profile, ignore_errors=True)
            self._temp_profile = None


WRONG_PASSWORD_HINTS = (
    "账号或密码错误",
    "帐号或密码错误",
    "密码错误",
    "密码不正确",
    "用户不存在",
    "账号不存在",
    "帐号不存在",
)


def browser_login(
    *,
    browser: str = "auto",
    email: str | None = None,
    password: str | None = None,
    timeout: int = 240,
    log: Log | None = None,
    headless: bool = False,
    account_kind: str = "auto",
    verify: Callable[[RequestsCookieJar], dict[str, Any]],
    get_credentials: Callable[[], tuple[str, str]] | None = None,
) -> tuple[RequestsCookieJar, dict[str, Any]]:
    """打开浏览器完成登录，返回 (cookies, member)。verify 用于校验登录态。"""
    say = log or (lambda message: None)
    if headless:
        # 命令行直接启动 Edge + --headless 在部分版本会立即退出；
        # 改用 Playwright 复用系统 Edge，同时支持三个登录标签。
        from .browser_login_playwright import (
            PlaywrightLoginError,
            playwright_login,
        )

        try:
            return playwright_login(
                browser=browser,
                email=email,
                password=password,
                timeout=timeout,
                log=log,
                account_kind=account_kind,
                verify=verify,
                get_credentials=get_credentials,
            )
        except PlaywrightLoginError as exc:
            raise BrowserLoginError(str(exc)) from exc
        except Exception as exc:
            raise BrowserLoginError(f"无窗口浏览器登录失败：{exc}") from exc

    # 统一从登录页进入：它同时提供 爱课程/手机号/邮箱 三个标签。
    start_url = LOGIN_PAGE
    session = BrowserLogin(
        browser=browser, log=log, headless=headless, start_url=start_url
    )
    # 任何失败（密码错误、超时、CDP 断开）都关闭本次拉起的窗口，
    # 避免旧窗口和端口文件污染下一次登录。
    try:
        session.launch()

        # 该配置目录此前已登录过：直接复用，无需再弹登录框
        for _ in range(8):
            time.sleep(0.8)
            jar = session.cookies()
            if not has_cookie(jar, "STUDY_SESS"):
                continue
            # 优先用 STUDY_INFO 解析，避免 getMocMember RPC 破坏 SPOC 上下文。
            member = member_from_cookies(jar)
            if not member:
                try:
                    member = verify(jar)
                except Exception:
                    member = None
            if member:
                if needs_spoc_warmup(jar):
                    try:
                        page = session._page_session()
                        session.warm_up_spoc(page, page)
                        jar = session.cookies()
                    except Exception:
                        pass
                say("浏览器配置中已有有效登录态，直接复用。")
                return jar, member

        page = session._page_session()
        session.open_login_dialog(page, account_kind=account_kind)

        if not (email and password) and get_credentials is not None:
            try:
                email, password = get_credentials()
            except Exception:
                email = password = None

        if email and password:
            session.fill_and_submit(page, email, password, account_kind=account_kind)
        else:
            say("请在打开的浏览器窗口中手动完成登录。")

        deadline = time.time() + timeout
        while time.time() < deadline:
            jar = session.cookies()
            if has_cookie(jar, "STUDY_SESS"):
                member = member_from_cookies(jar)
                if not member:
                    try:
                        member = verify(jar)
                    except Exception:
                        member = None
                if member:
                    if needs_spoc_warmup(jar):
                        session.warm_up_spoc(page, page)
                        jar = session.cookies()
                    return jar, member
            text = session.read_iframe_text(page)
            for hint in WRONG_PASSWORD_HINTS:
                if hint in text:
                    raise BrowserLoginError(f"登录失败：{hint}。")
            time.sleep(2)

        raise BrowserLoginError(
            "等待登录超时，已关闭登录窗口，请重试。"
        )
    finally:
        session.close()
