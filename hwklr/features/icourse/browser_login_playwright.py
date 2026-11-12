# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-12 10:00
# 文件名: browser_login_playwright.py
# 主要用途: 通过无头 Playwright 完成 icourse163 登录；Edge 启动失败时依次回退 Chrome/内置 Chromium。
# 文件版本: 4.6.0
"""无窗口（headless）浏览器登录。

`browser_login` 的可见窗口流程使用 CDP + 系统 Edge；无窗口模式若继续用
命令行参数启动 Edge，在部分 Windows/Edge 版本上会立即退出。这里改用
Playwright 启动系统 Edge，直接操作登录页的三个标签（爱课程/邮箱/手机号），
用于 GUI 的“后台登录”模式。
"""

from __future__ import annotations

import time
from typing import Any, Callable

from playwright.sync_api import Frame, Page, sync_playwright
from requests.cookies import RequestsCookieJar, create_cookie

from .browser_login import member_from_cookies, needs_spoc_warmup
from .config import BASE_URL, LOGIN_PAGE, USER_AGENT

Log = Callable[[str], None]

WRONG_PASSWORD_HINTS = (
    "账号或密码错误",
    "帐号或密码错误",
    "密码错误",
    "密码不正确",
    "用户不存在",
    "账号不存在",
    "帐号不存在",
    "该账号未注册",
)
CAPTCHA_HINTS = (
    "验证码",
    "滑块",
    "安全验证",
)
RATE_LIMIT_HINTS = (
    "操作过于频繁",
    "请稍后再试",
    "登录过于频繁",
)
SPOC_WARMUP_URL = BASE_URL + "/home.htm#/home/spocCourse"


class PlaywrightLoginError(Exception):
    """无窗口登录失败。"""


def _cookies_to_jar(cookies: list[dict[str, Any]]) -> RequestsCookieJar:
    jar = RequestsCookieJar()
    for item in cookies:
        domain = str(item.get("domain") or "")
        if not domain.lower().lstrip(".").endswith("icourse163.org"):
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


def _cookie_value(jar: RequestsCookieJar, name: str) -> str | None:
    for cookie in jar:
        if cookie.name == name:
            return cookie.value
    return None


def _click_visible_text(page: Page, text: str, timeout: int = 5000) -> bool:
    try:
        locator = page.get_by_text(text, exact=True)
        for item in locator.all():
            try:
                if item.is_visible():
                    item.click(timeout=timeout)
                    page.wait_for_timeout(600)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _visible(locator) -> bool:
    try:
        return locator.count() > 0 and locator.first.is_visible()
    except Exception:
        return False


def _find_urs_frame(page: Page, account_kind: str) -> Frame | None:
    account_selector = (
        "input[name=email][type=tel]:visible"
        if account_kind == "netease_phone"
        else "input[name=email][type=text]:visible"
    )
    password_selector = "input[type=password]:visible"
    for frame in page.frames:
        if "index_dl2_new" not in frame.url:
            continue
        try:
            if (
                _visible(frame.locator(account_selector))
                and _visible(frame.locator(password_selector))
            ):
                return frame
        except Exception:
            continue
    return None


def _fill_main_form(page: Page, account: str, password: str) -> None:
    account_input = page.locator("input[placeholder*='账号']:visible").first
    if not _visible(account_input):
        account_input = page.locator("input.ux-input[type=text]:visible").first
    password_input = page.locator("input[type=password]:visible").first
    if not _visible(account_input) or not _visible(password_input):
        raise PlaywrightLoginError("爱课程登录表单中找不到账号/密码输入框。")
    account_input.fill(account)
    password_input.fill(password)


def _submit_main_form(page: Page) -> None:
    for selector in (
        "span.ux-btn.submit-button:visible",
        "a.u-loginbtn:visible",
        ".j-submit:visible",
        "button[type=submit]:visible",
    ):
        locator = page.locator(selector)
        if _visible(locator):
            locator.first.click()
            return
    raise PlaywrightLoginError("爱课程登录表单中找不到「登录」按钮。")


def _fill_urs_form(frame: Frame, account: str, password: str, account_kind: str) -> None:
    account_selector = (
        "input[name=email][type=tel]:visible"
        if account_kind == "netease_phone"
        else "input[name=email][type=text]:visible"
    )
    account_input = frame.locator(account_selector).first
    password_input = frame.locator("input[type=password]:visible").first
    if not _visible(account_input) or not _visible(password_input):
        raise PlaywrightLoginError("网易通行证登录框中找不到账号/密码输入框。")
    account_input.fill(account)
    password_input.fill(password)


def _submit_urs_form(frame: Frame) -> None:
    for selector in (
        "a#submitBtn:visible",
        "a#dologin:visible",
        "a.u-loginbtn:visible",
    ):
        locator = frame.locator(selector)
        if _visible(locator):
            locator.first.click()
            return
    raise PlaywrightLoginError("网易通行证登录框中找不到「登录」按钮。")


def _page_text(page: Page, focus_frame: Frame | None = None) -> str:
    parts: list[str] = []
    try:
        parts.append(page.main_frame.locator("body").inner_text(timeout=2000))
    except Exception:
        pass
    if focus_frame is not None:
        try:
            parts.append(focus_frame.locator("body").inner_text(timeout=2000))
        except Exception:
            pass
    return "\n".join(parts)


def _detect_error(text: str) -> str:
    for hint in WRONG_PASSWORD_HINTS:
        if hint in text:
            return f"登录失败：{hint}。"
    if any(hint in text for hint in RATE_LIMIT_HINTS):
        return "登录请求过于频繁或站点限流，请稍后再试。"
    if any(hint in text for hint in CAPTCHA_HINTS):
        return (
            "登录需要短信/图片/滑块验证，后台模式无法完成；"
            "请改用“窗口登录”完成验证。"
        )
    return ""


def _warm_up_spoc(page: Page, log: Log) -> None:
    try:
        page.goto(SPOC_WARMUP_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(1500)
        log("已访问学校云首页，补齐 SPOC Cookie。")
    except Exception:
        pass


def playwright_login(
    *,
    browser: str = "auto",
    email: str | None = None,
    password: str | None = None,
    timeout: int = 240,
    log: Log | None = None,
    account_kind: str = "aiketang",
    verify: Callable[[RequestsCookieJar], dict[str, Any]],
    get_credentials: Callable[[], tuple[str, str]] | None = None,
) -> tuple[RequestsCookieJar, dict[str, Any]]:
    """用 Playwright 在无窗口 Edge 中完成登录，返回 (cookies, member)。"""
    say = log or (lambda message: None)
    if not (email and password) and get_credentials is not None:
        try:
            email, password = get_credentials()
        except Exception:
            email = password = None
    if not (email and password):
        raise PlaywrightLoginError(
            "后台登录需要账号和密码，请先在设置中填写。"
        )

    # 账号类型由用户显式选择，不再根据邮箱域名自动识别。
    kind = str(account_kind or "aiketang").strip().lower()
    if kind in ("mail", "netease"):
        kind = "netease"
    elif kind in ("phone", "netease_phone"):
        kind = "netease_phone"
    else:
        kind = "aiketang"

    with sync_playwright() as playwright:
        requested: str = (browser or "auto").lower()
        if requested == "chrome":
            channels: list[str | None] = ["chrome", "msedge", None]
        elif requested == "edge":
            channels = ["msedge", "chrome", None]
        else:
            channels = ["msedge", "chrome", None]
        # 去重但保留顺序；None 表示 Playwright 自带的 Chromium。
        unique_channels: list[str | None] = []
        for item in channels:
            if item not in unique_channels:
                unique_channels.append(item)
        browser_engine = None
        last_error: Exception | None = None
        launch_args: list[str] = [
            "--autoplay-policy=no-user-gesture-required",
            "--mute-audio",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        for channel in unique_channels:
            try:
                browser_engine = playwright.chromium.launch(
                    channel=channel,
                    headless=True,
                    args=launch_args,
                )
                if channel:
                    say(f"无头浏览器通道：{channel}")
                break
            except Exception as exc:
                last_error = exc
                say(f"无头浏览器通道 {channel or 'chromium'} 启动失败：{exc}")
        if browser_engine is None:
            raise PlaywrightLoginError(
                "无法启动无头浏览器（已尝试 Edge / Chrome / 内置 Chromium）：%s"
                % last_error
            )
        context = browser_engine.new_context(
            locale="zh-CN",
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        try:
            page.goto(LOGIN_PAGE, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2000)

            login_frame: Frame | None = None
            if kind == "aiketang":
                _click_visible_text(page, "爱课程登录", timeout=3000)
                _fill_main_form(page, email, password)
                say("已填写爱课堂账号和密码，提交登录…")
                _submit_main_form(page)
            else:
                tab = "手机号登录" if kind == "netease_phone" else "邮箱登录"
                _click_visible_text(page, tab, timeout=3000)
                page.wait_for_timeout(800)
                frame = None
                for _ in range(6):
                    frame = _find_urs_frame(page, kind)
                    if frame is not None:
                        break
                    page.wait_for_timeout(500)
                if frame is None:
                    raise PlaywrightLoginError(
                        f"没有找到「{tab}」的账号/密码输入框。"
                    )
                login_frame = frame
                _fill_urs_form(frame, email, password, kind)
                say(f"已填写{tab}账号和密码，提交登录…")
                _submit_urs_form(frame)

            deadline = time.time() + max(10, timeout)
            while time.time() < deadline:
                cookies = context.cookies()
                jar = _cookies_to_jar(cookies)
                if _cookie_value(jar, "STUDY_SESS"):
                    try:
                        member = member_from_cookies(jar)
                        if not member:
                            member = verify(jar)
                    except Exception:
                        member = None
                    if member:
                        try:
                            if needs_spoc_warmup(jar):
                                _warm_up_spoc(page, say)
                                jar = _cookies_to_jar(context.cookies())
                        except Exception:
                            pass
                        say("登录成功。")
                        return jar, member
                error = _detect_error(_page_text(page, login_frame))
                if error:
                    raise PlaywrightLoginError(error)
                page.wait_for_timeout(1500)

            raise PlaywrightLoginError(
                "等待登录超时。请改用“窗口登录”完成验证。"
            )
        finally:
            try:
                context.close()
            finally:
                browser_engine.close()


__all__ = ["PlaywrightLoginError", "playwright_login"]
