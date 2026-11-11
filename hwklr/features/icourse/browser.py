# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-11 10:00
# 文件名: browser.py
# 主要用途: 读取 Edge/Chrome/Brave/Firefox 本机 Cookie 数据库；单个来源失败时继续尝试其他来源。
# 文件版本: 4.4.3
"""从本机浏览器读取 icourse163.org 的登录 Cookie。

只读取 host 为 icourse163.org 的 Cookie，不会读取其他站点。
Chromium 系（Chrome / Edge / Brave / Chromium）读取 SQLite + DPAPI/AES-GCM；
Firefox 直接读取 cookies.sqlite。
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from requests.cookies import RequestsCookieJar, create_cookie

TARGET_DOMAIN = "icourse163.org"

BROWSER_LABELS = {
    "chrome": "Chrome",
    "edge": "Edge",
    "brave": "Brave",
    "chromium": "Chromium",
    "firefox": "Firefox",
}


class BrowserCookieError(Exception):
    """浏览器 Cookie 读取失败。"""


@dataclass
class CookieSource:
    browser: str
    profile: str
    db_path: Path

    @property
    def label(self) -> str:
        return f"{BROWSER_LABELS.get(self.browser, self.browser)} ({self.profile})"


# --------------------------------------------------------------------- 定位
def _chromium_user_dirs() -> dict[str, Path]:
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        return {
            "chrome": local / "Google/Chrome/User Data",
            "edge": local / "Microsoft/Edge/User Data",
            "brave": local / "BraveSoftware/Brave-Browser/User Data",
            "chromium": local / "Chromium/User Data",
        }
    if sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
        return {
            "chrome": base / "Google/Chrome",
            "edge": base / "Microsoft Edge",
            "brave": base / "BraveSoftware/Brave-Browser",
            "chromium": base / "Chromium",
        }
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return {
        "chrome": config / "google-chrome",
        "edge": config / "microsoft-edge",
        "brave": config / "BraveSoftware/Brave-Browser",
        "chromium": config / "chromium",
    }


def _firefox_profile_dir() -> Path | None:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", "")) / "Mozilla/Firefox/Profiles"
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support/Firefox/Profiles"
    else:
        base = Path.home() / ".mozilla/firefox"
    return base if base.is_dir() else None


def find_cookie_sources(browser: str | None = None) -> list[CookieSource]:
    """列出可用的 Cookie 数据库。browser 为 None 时查找全部。"""
    wanted = None
    if browser and browser != "auto":
        wanted = browser.lower()
        if wanted not in BROWSER_LABELS:
            raise BrowserCookieError(
                f"不支持的浏览器：{browser}（可选：auto, "
                + ", ".join(BROWSER_LABELS)
                + "）"
            )

    sources: list[CookieSource] = []
    for key, user_dir in _chromium_user_dirs().items():
        if wanted and wanted != key:
            continue
        if not user_dir.is_dir():
            continue
        for profile_dir in sorted(user_dir.iterdir()):
            if not profile_dir.is_dir():
                continue
            if profile_dir.name != "Default" and not profile_dir.name.startswith("Profile"):
                continue
            for rel in ("Network/Cookies", "Cookies"):
                db = profile_dir / rel
                if db.is_file():
                    sources.append(CookieSource(key, profile_dir.name, db))
                    break

    if not wanted or wanted == "firefox":
        ff = _firefox_profile_dir()
        if ff:
            for profile_dir in sorted(ff.iterdir()):
                db = profile_dir / "cookies.sqlite"
                if db.is_file():
                    sources.append(CookieSource("firefox", profile_dir.name, db))

    return sources


# --------------------------------------------------------------------- 解密
def _dpapi_unprotect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise BrowserCookieError("非 Windows 平台暂不支持 DPAPI 解密。")
    import ctypes
    import ctypes.wintypes as wt

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    input_buffer = ctypes.create_string_buffer(data)
    blob_in = DataBlob(len(data), ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = DataBlob()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise BrowserCookieError(
            "无法解密浏览器密钥（DPAPI 失败），请在当前 Windows 用户下运行。"
        )
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _mac_key(browser: str) -> bytes:
    """macOS 上从 Keychain 读取 Chromium 的 Safe Storage 密钥。"""
    import subprocess

    service = {
        "chrome": "Chrome Safe Storage",
        "edge": "Microsoft Edge Safe Storage",
        "brave": "Brave Safe Storage",
        "chromium": "Chromium Safe Storage",
    }.get(browser, "Chrome Safe Storage")
    try:
        password = subprocess.check_output(
            ["security", "find-generic-password", "-w", "-s", service],
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BrowserCookieError(f"无法从 Keychain 读取 {service}。") from exc
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(algorithm=hashes.SHA1(), length=16, salt=b"saltysalt", iterations=1003)
    return kdf.derive(password)


def _chromium_master_key(user_data_dir: Path, browser: str) -> bytes:
    local_state = user_data_dir / "Local State"
    try:
        data = json.loads(local_state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrowserCookieError(f"无法读取 {local_state}。") from exc

    encoded = data.get("os_crypt", {}).get("encrypted_key")
    if not encoded:
        raise BrowserCookieError("浏览器没有 os_crypt.encrypted_key，无法解密 Cookie。")
    raw = base64.b64decode(encoded)
    if raw[:5] == b"DPAPI":
        return _dpapi_unprotect(raw[5:])
    if sys.platform == "win32":
        return _dpapi_unprotect(raw)
    if sys.platform == "darwin":
        return _mac_key(browser)
    # Linux 通常使用固定密码 "peanuts"
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(algorithm=hashes.SHA1(), length=16, salt=b"saltysalt", iterations=1)
    return kdf.derive(b"peanuts")


def _decrypt_chromium_value(value: bytes, key: bytes, label: str) -> str:
    if not value:
        return ""
    if value[:3] in (b"v10", b"v11"):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            nonce, payload = value[3:15], value[15:]
            return AESGCM(key).decrypt(nonce, payload, None).decode("utf-8", "replace")
        except Exception as exc:  # 解密失败通常意味着密钥不匹配或数据损坏
            raise BrowserCookieError(f"Cookie 解密失败（{label}）。") from exc
    if value[:3] == b"v20":
        raise BrowserCookieError(
            "浏览器使用了 App-Bound 加密（v20），无法自动解密。\n"
            "请改用“导入 Cookie”功能手动导入。"
            "或换用 Firefox 登录后重试。"
        )
    return value.decode("utf-8", "replace")


# --------------------------------------------------------------------- 读取
def _copy_database(db_path: Path) -> tuple[Path, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory(prefix="moocok-cookies-")
    dest = Path(tmp.name) / db_path.name
    try:
        shutil.copy2(db_path, dest)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(db_path) + suffix)
            if sidecar.exists():
                try:
                    shutil.copy2(sidecar, Path(str(dest) + suffix))
                except OSError:
                    pass
    except PermissionError as exc:
        tmp.cleanup()
        raise BrowserCookieError(
            f"无法读取 {db_path.name}，浏览器正在占用该文件。\n"
            "请完全退出浏览器（包括托盘/后台进程）后再试一次。"
        ) from exc
    except OSError as exc:
        tmp.cleanup()
        raise BrowserCookieError(f"复制 Cookie 数据库失败：{exc}") from exc
    return dest, tmp


def _user_data_dir(db_path: Path) -> Path:
    for parent in db_path.parents:
        if (parent / "Local State").is_file():
            return parent
    raise BrowserCookieError(f"无法定位浏览器的 Local State（{db_path}）。")


def _read_chromium(source: CookieSource) -> RequestsCookieJar:
    user_data_dir = _user_data_dir(source.db_path)
    key = _chromium_master_key(user_data_dir, source.browser)
    dest, tmp = _copy_database(source.db_path)
    try:
        con = sqlite3.connect(str(dest))
        try:
            rows = con.execute(
                "SELECT host_key, name, encrypted_value, path, expires_utc, is_secure "
                "FROM cookies WHERE host_key LIKE ?",
                (f"%{TARGET_DOMAIN}",),
            ).fetchall()
        finally:
            con.close()
    finally:
        tmp.cleanup()

    jar = RequestsCookieJar()
    for host, name, encrypted, path, expires_utc, secure in rows:
        value = _decrypt_chromium_value(bytes(encrypted or b""), key, name)
        # Chromium 的 expires_utc 是 1601-01-01 起的微秒数；0 表示会话 Cookie
        expires = int(expires_utc / 1_000_000 - 11644473600) if expires_utc else None
        if expires is not None and expires <= 0:
            continue
        jar.set_cookie(
            create_cookie(
                name=name,
                value=value,
                domain=host,
                path=path or "/",
                secure=bool(secure),
                expires=expires,
            )
        )
    return jar


def _read_firefox(source: CookieSource) -> RequestsCookieJar:
    dest, tmp = _copy_database(source.db_path)
    try:
        con = sqlite3.connect(str(dest))
        try:
            rows = con.execute(
                "SELECT host, name, value, path, expiry, isSecure "
                "FROM moz_cookies WHERE host LIKE ?",
                (f"%{TARGET_DOMAIN}",),
            ).fetchall()
        finally:
            con.close()
    finally:
        tmp.cleanup()

    jar = RequestsCookieJar()
    for host, name, value, path, expiry, secure in rows:
        jar.set_cookie(
            create_cookie(
                name=name,
                value=value or "",
                domain=host,
                path=path or "/",
                secure=bool(secure),
                expires=expiry or None,
            )
        )
    return jar


def read_cookies(source: CookieSource) -> RequestsCookieJar:
    if source.browser == "firefox":
        return _read_firefox(source)
    return _read_chromium(source)


def iter_browser_cookies(
    browser: str | None = None,
    errors: list[str] | None = None,
) -> Iterator[tuple[CookieSource, RequestsCookieJar]]:
    """逐个产出可用的 (来源, CookieJar)。

    单个浏览器/配置读取失败（被占用、App-Bound 加密等）只记录原因并继续
    尝试下一个来源，不再让第一个失败源终止整条导入链。

    Args:
        browser: ``auto`` 或浏览器名。
        errors: 可选的失败原因收集列表。

    Yields:
        ``(来源, CookieJar)``。
    """
    sources = find_cookie_sources(browser)
    if not sources:
        target = BROWSER_LABELS.get((browser or "").lower(), browser or "浏览器")
        raise BrowserCookieError(
            f"没有找到 {target} 的 Cookie 数据库。请确认已安装并在其中登录过 icourse163.org。"
        )
    for source in sources:
        try:
            jar = read_cookies(source)
        except BrowserCookieError as exc:
            if errors is not None:
                errors.append("%s：%s" % (source.label, exc))
            continue
        if jar:
            yield source, jar
