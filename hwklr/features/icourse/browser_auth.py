# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: browser_auth.py
# 主要用途: Cookie 注入、登录态校验与 Playwright storage_state 导出。
# 文件版本: 4.0.0
"""把保存的 Cookie 同步进调试 Edge，或导出无头模式登录态。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .browser_session import BrowserSession, BrowserSessionError, default_storage_state
from .client import AuthError
from .session_store import SavedSession, load_session
from .config import BASE_URL, session_file

# 只注入 .icourse163.org：www./reg. 子域的旧 Cookie 会造成同名重复，
# 服务端可能取到未登录的那一份，导致学习页被判为未登录。
TARGET_DOMAIN = ".icourse163.org"
LOGIN_PAGE_TIMEOUT_MS = 15_000


def cookie_dicts(saved: SavedSession) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for cookie in saved.cookies:
        name = cookie.get("name")
        domain = str(cookie.get("domain") or "")
        if not name or not domain:
            continue
        if domain.lower() != TARGET_DOMAIN:
            continue
        item: dict[str, Any] = {
            "name": name,
            "value": cookie.get("value", ""),
            "path": cookie.get("path") or "/",
            "secure": bool(cookie.get("secure")),
            # 页面 JS 需要读取 NTESSTUDYSI 作为 csrfKey；其余保持 HttpOnly。
            "httpOnly": name != "NTESSTUDYSI",
            "domain": domain,
        }
        expires = cookie.get("expires")
        if expires and int(expires) > 0:
            item["expires"] = int(expires)
        items.append(item)
    return items


def sync_saved_session(
    session: BrowserSession, saved: SavedSession | None = None
) -> int:
    """清空调试浏览器 Cookie，注入已保存会话，返回注入数量。"""
    saved = saved or load_session()
    if saved is None:
        raise RuntimeError("没有已保存的会话，请先登录中国大学慕课")
    cookies = cookie_dicts(saved)
    if not cookies:
        raise RuntimeError("保存的会话里没有 icourse163 Cookie")
    session.context.clear_cookies()
    session.context.add_cookies(cookies)
    return len(cookies)


def page_for_icourse(session: BrowserSession):
    page = session.find_page("icourse163")
    if page is None:
        page = session.context.new_page()
        page.goto(
            BASE_URL + "/",
            wait_until="domcontentloaded",
            timeout=LOGIN_PAGE_TIMEOUT_MS,
        )
    return page


def login_user_id(page) -> str:
    """读取站点注入的当前登录用户 ID；未登录时为空字符串。

    ``window.webUser`` 是 icourse163 前端在登录后注入的全局对象，
    MOOC 和 SPOC 页面都有；未登录时为 null。相比调用 memberBean
    （未登录也可能返回 ``{"code":0,"result":null}``）可靠得多。
    """
    try:
        value = page.evaluate(
            """() => (window.webUser && window.webUser.id)
                     ? String(window.webUser.id) : ''"""
        )
    except Exception:
        return ""
    return str(value or "")


def verify_login(session: BrowserSession) -> bool:
    """验证浏览器会话真实有效。

    先用当前页面读取 ``window.webUser``；如果当前页不是首页且没有该
    全局对象（部分页面不会注入），再回首页读一次。全程最多两次 15 秒
    导航，不再使用无超时的页面内 fetch。
    """
    try:
        page = page_for_icourse(session)
    except Exception:
        return False
    url = str(getattr(page, "url", "") or "")
    if "icourse163.org" not in url:
        try:
            page.goto(
                BASE_URL + "/",
                wait_until="domcontentloaded",
                timeout=LOGIN_PAGE_TIMEOUT_MS,
            )
        except Exception:
            return False
        url = str(getattr(page, "url", "") or "")
    if login_user_id(page):
        return True
    # 学习页/课程页有时不注入 window.webUser，回首页再确认一次。
    if url.rstrip("/") != BASE_URL:
        try:
            page.goto(
                BASE_URL + "/",
                wait_until="domcontentloaded",
                timeout=LOGIN_PAGE_TIMEOUT_MS,
            )
        except Exception:
            return False
    return bool(login_user_id(page))


def ensure_storage_state_login(path: Path | str) -> None:
    """在启动多个无头 worker 前，先验证 storage_state 是否仍登录。

    只启动一个探针浏览器；失败立即抛 AuthError，避免 N 个 worker
    各自带着失效 Cookie 空等。
    """
    try:
        with BrowserSession(
            headless=True, attach=False, storage_state=path
        ) as session:
            if verify_login(session):
                return
    except BrowserSessionError as exc:
        raise AuthError(f"无头浏览器启动失败：{exc}") from exc
    except Exception as exc:
        raise AuthError(f"无头登录态校验失败：{exc}") from exc
    raise AuthError(
        "无头登录态已失效（浏览器打开后未登录）。请重新运行 "
        "请重新登录中国大学慕课，或重新导入 Cookie。"
    )


def storage_state_payload(saved: SavedSession) -> dict[str, Any]:
    """把保存的 Cookie 转成 Playwright storage_state（不依赖浏览器）。

    SPOC 页面需要 ``www.icourse163.org`` 等子域的同名 Cookie；
    这里保留所有 ``icourse163.org`` 域（含重复名），不要像
    ``cookie_dicts`` 那样只保留 ``.icourse163.org``。
    """
    if saved is None:
        raise RuntimeError("没有已保存的会话，请先登录中国大学慕课")
    cookies: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for cookie in saved.cookies:
        name = cookie.get("name")
        domain = str(cookie.get("domain") or "")
        if not name or not domain:
            continue
        if not domain.lower().lstrip(".").endswith("icourse163.org"):
            continue
        path = cookie.get("path") or "/"
        key = (str(name), domain, path)
        if key in seen:
            continue
        seen.add(key)
        expires = cookie.get("expires")
        cookies.append(
            {
                "name": name,
                "value": cookie.get("value", ""),
                "domain": domain,
                "path": path,
                "expires": int(expires) if expires and int(expires) > 0 else -1,
                "httpOnly": str(name) != "NTESSTUDYSI",
                "secure": bool(cookie.get("secure")),
                "sameSite": "Lax",
            }
        )
    return {"cookies": cookies, "origins": []}


def export_saved_storage_state(
    path: Path | str | None = None, saved: SavedSession | None = None
) -> Path:
    """直接从 session.json 生成 storage_state，供无头 worker 使用。"""
    saved = saved or current_saved_session()
    payload = storage_state_payload(saved)
    target = Path(path) if path else default_storage_state()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target


def export_storage_state(
    session: BrowserSession, path: Path | str | None = None
) -> Path:
    return session.export_storage_state(path or default_storage_state())


def current_saved_session() -> SavedSession | None:
    return load_session(session_file())
