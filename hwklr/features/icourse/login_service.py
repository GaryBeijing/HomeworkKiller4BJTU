# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: login_service.py
# 主要用途: 编排慕课账号登录、窗口/无头浏览器登录、本机 Cookie 导入与已保存会话加载。
# 文件版本: 4.1.1
"""慕课登录与会话服务。

- 账号登录统一走 icourse163 登录页（Playwright/系统 Edge），
  真实浏览器负责加密、指纹与风控。
- 本机 Cookie 导入复用原型 ``browser.py`` 的 Chromium/Firefox 读取逻辑。
- 会话保存在 ``app_root()/auth/icourse_session.json``，并导出无头模式所需的
  ``storage_state``。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from . import accounts, browser_auth, config
from .browser import BrowserCookieError, iter_browser_cookies
from .browser_login import BrowserLoginError, browser_login, member_from_cookies
from .client import AuthError, MoocClient
from .session_store import (
    SavedSession,
    cookies_to_list,
    has_login_cookies,
    load_session,
    save_session,
)

__version__ = "4.1.1"
__author__ = "Gary"
__all__ = [
    "LoginError",
    "ensure_storage_state",
    "ensure_storage_state_valid",
    "import_browser_cookies",
    "load_client",
    "login_with_credentials",
    "member_summary",
    "session_path",
    "logout",
]

MEMBER_KEYS = ("id", "nickName", "nickname", "realName", "email", "loginId", "memberId")
Log = Callable[[str], None]


class LoginError(AuthError):
    """面向 UI 的登录错误。"""


def member_summary(member: dict[str, Any]) -> dict[str, Any]:
    """提取用户信息中的可展示字段。

    Args:
        member: 原始用户信息。

    Returns:
        过滤后的字典。
    """
    return {
        key: member[key]
        for key in MEMBER_KEYS
        if member.get(key) not in (None, "")
    }


def session_path() -> Path:
    """返回主会话文件路径。

    Returns:
        ``auth/icourse_session.json``。
    """
    return config.session_file()


def load_client(
    *,
    path: Path | None = None,
    log: Log | None = None,
) -> tuple[MoocClient, dict[str, Any]]:
    """加载已保存会话并构造客户端。

    Args:
        path: 会话路径；默认主会话。
        log: 日志回调。

    Returns:
        ``(客户端, 用户信息)``。

    Raises:
        LoginError: 未登录或会话缺少登录 Cookie。
    """
    target: Path = Path(path) if path else session_path()
    saved: SavedSession | None = load_session(target)
    if saved is None or not has_login_cookies(saved):
        raise LoginError("尚未登录中国大学慕课，请先登录或导入 Cookie。")
    client: MoocClient = MoocClient.from_cookie_jar(saved.jar)
    member: dict[str, Any] = dict(saved.user)
    try:
        if member.get("id"):
            client._member_id_cache = int(member["id"])
    except (TypeError, ValueError):
        pass
    if not member:
        member = client.get_member()
        save_session(SavedSession(cookies=saved.cookies, user=member_summary(member)), target)
        _export_storage_state(target, log)
    return client, member


def _export_storage_state(path: Path, log: Log | None) -> None:
    """从会话文件导出 Playwright storage_state。

    Args:
        path: 会话文件。
        log: 日志回调。
    """
    saved: SavedSession | None = load_session(path)
    if saved is None:
        return
    try:
        target: Path = browser_auth.export_saved_storage_state(
            config.storage_state_file(), saved
        )
        if log:
            log("已生成无头登录态：%s" % target.name)
    except Exception as exc:
        if log:
            log("生成无头登录态失败：%s" % exc)


def ensure_storage_state(log: Log | None = None) -> Path:
    """从已保存会话生成无头模式登录态。

    Args:
        log: 日志回调。

    Returns:
        storage_state 文件路径。

    Raises:
        LoginError: 没有已保存会话。
    """
    saved: SavedSession | None = load_session(session_path())
    if saved is None or not has_login_cookies(saved):
        raise LoginError("未找到已保存的登录会话，请先登录或导入 Cookie。")
    try:
        target: Path = browser_auth.export_saved_storage_state(
            config.storage_state_file(), saved
        )
    except Exception as exc:
        raise LoginError("生成无头登录态失败：%s" % exc) from exc
    if log:
        log("已生成无头登录态：%s" % target.name)
    return target


def ensure_storage_state_valid(log: Log | None = None) -> Path:
    """生成并验证无头 storage_state 是否仍处于登录状态。

    Args:
        log: 日志回调。

    Returns:
        storage_state 文件路径。

    Raises:
        LoginError: 会话缺失、浏览器启动失败或登录态已失效。
    """
    from .browser_auth import ensure_storage_state_login

    target: Path = ensure_storage_state(log)
    try:
        ensure_storage_state_login(target)
    except Exception as exc:
        raise LoginError("登录状态校验失败：%s" % exc) from exc
    return target


def _verify_cookie_jar(jar: Any) -> dict[str, Any]:
    """登录后校验 Cookie；优先从 STUDY_INFO 解析，避免破坏 SPOC 上下文。

    Args:
        jar: requests CookieJar。

    Returns:
        用户信息。

    Raises:
        AuthError: Cookie 不构成有效登录。
    """
    member: dict[str, Any] = member_from_cookies(jar)
    if member:
        return member
    return MoocClient.from_cookie_jar(jar).get_member()


def login_with_credentials(
    account: str,
    password: str,
    *,
    account_type: str = "auto",
    browser: str = "auto",
    headless: bool = False,
    timeout: int = 240,
    log: Log | None = None,
    cancel: threading.Event | None = None,
) -> dict[str, Any]:
    """使用账号密码登录并保存会话。

    Args:
        account: 账号。
        password: 密码。
        account_type: ``auto/icourse/mail/phone``。
        browser: 浏览器类型。
        headless: 是否无头。
        timeout: 等待登录秒数。
        log: 日志回调。
        cancel: 取消事件；在登录前后检查。

    Returns:
        用户信息。

    Raises:
        LoginError: 账号为空、取消或登录失败。
    """
    account = str(account or "").strip()
    password = str(password or "")
    if headless and (not account or not password):
        raise LoginError("后台登录需要先在设置中填写账号和密码。")
    if cancel is not None and cancel.is_set():
        raise LoginError("登录已取消。")
    account_kind: str = accounts.resolve_account_type(account_type, account)
    if log:
        log("正在使用%s登录…" % ("无头浏览器" if headless else "浏览器窗口"))

    def get_credentials() -> tuple[str, str]:
        return account, password

    try:
        jar, member = browser_login(
            browser=browser,
            email=account or None,
            password=password or None,
            timeout=max(30, int(timeout)),
            log=log,
            headless=headless,
            account_kind=account_kind,
            verify=_verify_cookie_jar,
            get_credentials=get_credentials,
        )
    except BrowserLoginError as exc:
        raise LoginError(str(exc)) from exc
    except Exception as exc:
        raise LoginError("登录失败：%s" % exc) from exc
    if cancel is not None and cancel.is_set():
        raise LoginError("登录已取消。")

    summary: dict[str, Any] = member_summary(member)
    save_session(
        SavedSession(cookies=cookies_to_list(jar), user=summary),
        session_path(),
    )
    _export_storage_state(session_path(), log)
    return summary


def import_browser_cookies(
    *,
    browser: str = "auto",
    log: Log | None = None,
    cancel: threading.Event | None = None,
) -> dict[str, Any]:
    """从本机浏览器 Cookie 数据库导入登录态。

    Args:
        browser: ``auto`` 或浏览器名。
        log: 日志回调。
        cancel: 取消事件。

    Returns:
        用户信息。

    Raises:
        LoginError: 未找到可用 Cookie 或读取失败。
    """
    if log:
        log("正在读取本机浏览器 Cookie…")
    try:
        sources = list(iter_browser_cookies(browser))
    except BrowserCookieError as exc:
        raise LoginError(str(exc)) from exc
    except Exception as exc:
        raise LoginError("读取本机 Cookie 失败：%s" % exc) from exc

    for source, jar in sources:
        if cancel is not None and cancel.is_set():
            raise LoginError("登录已取消。")
        icourse_cookies = [
            cookie
            for cookie in jar
            if "icourse163.org" in str(cookie.domain or "").lower()
        ]
        if not icourse_cookies:
            continue
        saved = SavedSession(cookies=cookies_to_list(jar))
        if not has_login_cookies(saved):
            continue
        member = member_from_cookies(jar)
        summary = member_summary(member)
        save_session(
            SavedSession(cookies=cookies_to_list(jar), user=summary),
            session_path(),
        )
        _export_storage_state(session_path(), log)
        if log:
            log("已从 %s 导入登录 Cookie。" % source.label)
        return summary
    raise LoginError(
        "未在浏览器中找到中国大学慕课登录 Cookie，请先在该浏览器登录 icourse163.org。"
    )


def logout() -> bool:
    """删除会话与无头登录态。

    Returns:
        是否删除了主会话文件。
    """
    removed: bool = False
    for path in (
        config.session_file(),
        config.spoc_session_file(),
        config.storage_state_file(),
    ):
        try:
            path.unlink()
            removed = True
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return removed
