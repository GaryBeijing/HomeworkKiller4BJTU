# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: session_store.py
# 主要用途: 慕课会话 Cookie 的保存、读取与删除。
# 文件版本: 4.0.0
"""会话持久化：保存/恢复登录 Cookie，避免每次输入密码。"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from requests.cookies import RequestsCookieJar, create_cookie

from .config import session_file


def cookies_to_list(jar: RequestsCookieJar) -> list[dict[str, Any]]:
    out = []
    for cookie in jar:
        out.append(
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain or "",
                "path": cookie.path or "/",
                "secure": bool(cookie.secure),
                "expires": cookie.expires,
            }
        )
    return out


def cookies_from_list(items: list[dict[str, Any]]) -> RequestsCookieJar:
    jar = RequestsCookieJar()
    for item in items:
        name = item.get("name")
        if not name:
            continue
        jar.set_cookie(
            create_cookie(
                name=name,
                value=item.get("value", ""),
                domain=item.get("domain") or "",
                path=item.get("path") or "/",
                secure=bool(item.get("secure")),
                expires=item.get("expires"),
            )
        )
    return jar


def cookies_from_string(raw: str, domain: str = ".icourse163.org") -> RequestsCookieJar:
    """解析浏览器里复制的 `Cookie: a=1; b=2` 字符串或 Netscape 格式。"""
    jar = RequestsCookieJar()
    raw = raw.strip()
    if not raw:
        return jar

    if "\t" in raw:
        # Netscape cookies.txt 格式：domain \t flag \t path \t secure \t expires \t name \t value
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            dom, _flag, path, secure, expires, name, value = parts[:7]
            try:
                exp = int(float(expires)) if expires else None
            except ValueError:
                exp = None
            jar.set_cookie(
                create_cookie(
                    name=name,
                    value=value,
                    domain=dom,
                    path=path or "/",
                    secure=secure.upper() == "TRUE",
                    expires=exp,
                )
            )
        if jar:
            return jar

    if raw.lower().startswith("cookie:"):
        raw = raw.split(":", 1)[1]
    for part in raw.replace("\n", ";").split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name, value = name.strip(), value.strip()
        if name:
            jar.set_cookie(
                create_cookie(
                    name=name,
                    value=value,
                    domain=domain,
                    path="/",
                )
            )
    return jar


LOGIN_COOKIE_NAMES = ("STUDY_SESS", "STUDY_INFO")


def has_login_cookies(saved: "SavedSession | None") -> bool:
    """保存的会话是否至少带有一个登录 Cookie（不校验是否过期）。"""
    if saved is None:
        return False
    names = {str(cookie.get("name") or "") for cookie in saved.cookies}
    return bool(names & set(LOGIN_COOKIE_NAMES))


@dataclass
class SavedSession:
    cookies: list[dict[str, Any]] = field(default_factory=list)
    user: dict[str, Any] = field(default_factory=dict)
    saved_at: str = ""
    version: int = 1

    @property
    def jar(self) -> RequestsCookieJar:
        return cookies_from_list(self.cookies)

    def user_label(self) -> str:
        for key in ("nickName", "nickname", "realName", "loginId", "email"):
            value = self.user.get(key)
            if value:
                return str(value)
        return ""


def load_session(path: Path | None = None) -> SavedSession | None:
    path = path or session_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return SavedSession(
        cookies=data.get("cookies") or [],
        user=data.get("user") or {},
        saved_at=data.get("saved_at") or "",
        version=int(data.get("version") or 1),
    )


def save_session(session: SavedSession, path: Path | None = None) -> Path:
    path = path or session_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    session.saved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    payload = {
        "version": 1,
        "saved_at": session.saved_at,
        "user": session.user,
        "cookies": session.cookies,
    }
    fd, tmp_name = tempfile.mkstemp(prefix=".session-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def delete_session(path: Path | None = None) -> bool:
    path = path or session_file()
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
