# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-11 21:00
# 最后更新: 2026-11-12 14:10
# 文件名: core.py
# 主要用途: 平台无关的更新核心：版本检查、资产筛选、ZIP 下载校验、staging 目录归一化与安装状态机。
# 文件版本: 4.6.2
"""跨平台自动更新核心。"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

import requests

from hwklr import DEV_BUILD, __version__ as APP_VERSION
from hwklr.config import data_root, load_config

from .installers import get_platform_installer
from .installers.base import InstallerError, PlatformInstaller
from .models import PreparedUpdate, ReleaseAsset, ReleaseInfo

__version__ = "4.6.2"
__author__ = "Gary"
__all__ = [
    "AUTO_ASSET_RE",
    "MD5_ASSET_RE",
    "UpdateService",
    "cleanup_incomplete_update",
    "parse_version",
    "select_auto_asset",
    "select_md5_asset",
    "updates_dir",
]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_GITHUB_API: Final[str] = (
    "https://api.github.com/repos/GaryBeijing/HomeworkKiller4BJTU/releases/latest"
)
_GITCODE_API: Final[str] = (
    "https://api.gitcode.com/api/v5/repos/weixin_68744568/"
    "HomeworkKiller4BJTU/releases/latest"
)
_USER_AGENT: Final[str] = "HomeworkKiller4BJTU/%s" % APP_VERSION
_HTTP_TIMEOUT: Final[tuple[float, float]] = (5.0, 15.0)
_RACE_WAIT_SECONDS: Final[float] = 12.0
_MAX_NOTES_CHARS: Final[int] = 20_000
_MAX_ASSET_BYTES: Final[int] = 512 * 1024 * 1024
_SAFE_NAME: Final[re.Pattern[str]] = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# 用户指定：自动更新只接受 hwklr4bjtu-<platform>-<arch>-vX.Y.Z*.zip。
AUTO_ASSET_RE: Final[re.Pattern[str]] = re.compile(
    r"^(hwklr4bjtu)-(windows|macos)-(arm64|x64)-v([0-9]\.){2}[0-9].*?\.zip$",
    re.IGNORECASE,
)
MD5_ASSET_RE: Final[re.Pattern[str]] = re.compile(
    r"^(hwklr4bjtu)-(windows|macos)-(arm64|x64)-md5-v([0-9]\.){2}[0-9].*?\.txt$",
    re.IGNORECASE,
)
_EXCLUDED_ASSET_WORDS: Final[tuple[str, ...]] = (
    "manual",
    "setup",
    "installer",
    "portable",
    "source",
)


def updates_dir() -> Path:
    """返回更新工作目录（数据根目录下，保证可写）。"""
    return data_root() / "updates"


def _download_dir() -> Path:
    """返回下载目录。"""
    return updates_dir() / "download"


def _staging_dir() -> Path:
    """返回 staging 根目录。"""
    return updates_dir() / "staging"


def _pending_file() -> Path:
    """返回 pending.json。"""
    return updates_dir() / "pending.json"


def _idle_state() -> dict[str, Any]:
    """返回空闲状态。"""
    return {
        "status": "idle",
        "current": str(APP_VERSION),
        "latest": "",
        "source": "",
        "notes": "",
        "progress": 0,
        "error": "",
        "asset_name": "",
        "asset_size": 0,
        "can_install": False,
        "prepared": False,
        "pending": False,
        "download_path": "",
        "staging_path": "",
        "release_url": "",
    }


def parse_version(text: Any) -> tuple[int, int, int] | None:
    """解析版本号前三段，忽略 v 前缀与第四段。"""
    match: re.Match[str] | None = re.match(
        r"^[vV]?(\d+)\.(\d+)\.(\d+)", str(text or "").strip()
    )
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _is_newer(remote: Any, current: Any) -> bool:
    """判断远端版本是否更高。"""
    remote_parts = parse_version(remote)
    current_parts = parse_version(current)
    if remote_parts is None or current_parts is None:
        return False
    return remote_parts > current_parts


def _safe_asset_name(name: str) -> str:
    """把资产名转换为安全文件名。"""
    base: str = Path(str(name or "")).name
    return _SAFE_NAME.sub("_", base).strip(" .") or "update.zip"


def _download_url_allowed(url: str) -> bool:
    """只允许受信任的 HTTPS 下载主机。"""
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host: str = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in {"github.com", "api.github.com", "gitcode.com", "api.gitcode.com"}:
        return True
    return host.endswith(".githubusercontent.com") or host.endswith(".gitcode.com")


def _normalize_release(payload: Any, source: str) -> ReleaseInfo | None:
    """归并 GitHub/GitCode release JSON。"""
    if not isinstance(payload, dict):
        return None
    tag: str = str(payload.get("tag_name") or payload.get("name") or "").strip()
    if not tag:
        return None
    assets: list[ReleaseAsset] = []
    raw_assets: Any = payload.get("assets")
    if isinstance(raw_assets, list):
        for item in raw_assets:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "").lower() == "source":
                continue
            name: str = str(item.get("name") or "").strip()
            url: str = str(
                item.get("browser_download_url") or item.get("url") or ""
            ).strip()
            if not name or not url:
                continue
            try:
                size: int = int(item.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            assets.append(
                ReleaseAsset(
                    name=name,
                    url=url,
                    size=max(0, size),
                    digest=str(item.get("digest") or ""),
                )
            )
    return ReleaseInfo(
        tag=tag,
        source=source,
        notes=str(payload.get("body") or "")[:_MAX_NOTES_CHARS],
        release_url=str(payload.get("html_url") or ""),
        assets=assets,
    )


def select_auto_asset(
    assets: list[ReleaseAsset],
    *,
    platform: str,
    arch: str,
    version: str,
    dev_build: bool = DEV_BUILD,
) -> ReleaseAsset | None:
    """按用户约定的文件名正则选择自动更新 ZIP。

    只接受 ``hwklr4bjtu-<platform>-<arch>-vX.Y.Z*.zip``；手动 exe/中文名
    天然不匹配。正式构建忽略 -dev；没有精确版本名时只有唯一候选才使用。
    """
    matches: list[ReleaseAsset] = []
    for asset in assets:
        match: re.Match[str] | None = AUTO_ASSET_RE.fullmatch(asset.name)
        if match is None:
            continue
        if match.group(2).lower() != platform or match.group(3).lower() != arch:
            continue
        lower: str = asset.name.lower()
        if any(word in lower for word in _EXCLUDED_ASSET_WORDS):
            continue
        if not _download_url_allowed(asset.url):
            continue
        matches.append(asset)
    if not matches:
        return None
    base_name: str = "hwklr4bjtu-%s-%s-v%s" % (
        platform,
        arch,
        str(version).lstrip("vV"),
    )
    if dev_build:
        expected_dev: str = (base_name + "-dev.zip").lower()
        dev_exact: list[ReleaseAsset] = [
            asset for asset in matches if asset.name.lower() == expected_dev
        ]
        if dev_exact:
            return dev_exact[0]
        dev: list[ReleaseAsset] = [
            asset for asset in matches if "-dev" in asset.name.lower()
        ]
        if len(dev) == 1:
            return dev[0]
        return None
    expected: str = (base_name + ".zip").lower()
    exact: list[ReleaseAsset] = [
        asset for asset in matches if asset.name.lower() == expected
    ]
    if exact:
        return exact[0]
    non_dev: list[ReleaseAsset] = [
        asset for asset in matches if "-dev" not in asset.name.lower()
    ]
    return non_dev[0] if len(non_dev) == 1 else None


def select_md5_asset(
    assets: list[ReleaseAsset],
    *,
    platform: str,
    arch: str,
    version: str,
    dev_build: bool = DEV_BUILD,
) -> ReleaseAsset | None:
    """选择与当前平台/版本匹配的 md5 文件。

    约定名：``hwklr4bjtu-<platform>-<arch>-md5-vX.Y.Z*.txt``。
    """
    matches: list[ReleaseAsset] = []
    for asset in assets:
        match: re.Match[str] | None = MD5_ASSET_RE.fullmatch(asset.name)
        if match is None:
            continue
        if match.group(2).lower() != platform or match.group(3).lower() != arch:
            continue
        if not _download_url_allowed(asset.url):
            continue
        matches.append(asset)
    if not matches:
        return None
    base_name: str = "hwklr4bjtu-%s-%s-md5-v%s" % (
        platform,
        arch,
        str(version).lstrip("vV"),
    )
    if dev_build:
        expected_dev: str = (base_name + "-dev.txt").lower()
        dev_exact: list[ReleaseAsset] = [
            asset for asset in matches if asset.name.lower() == expected_dev
        ]
        if dev_exact:
            return dev_exact[0]
        dev: list[ReleaseAsset] = [
            asset for asset in matches if "-dev" in asset.name.lower()
        ]
        return dev[0] if len(dev) == 1 else None
    expected: str = (base_name + ".txt").lower()
    exact: list[ReleaseAsset] = [
        asset for asset in matches if asset.name.lower() == expected
    ]
    if exact:
        return exact[0]
    non_dev: list[ReleaseAsset] = [
        asset for asset in matches if "-dev" not in asset.name.lower()
    ]
    return non_dev[0] if len(non_dev) == 1 else None


def _read_json(path: Path) -> dict[str, Any] | None:
    """读取 JSON 对象。"""
    try:
        with path.open(encoding="utf-8-sig") as fp:
            data: Any = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """原子写入 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
        fp.write("\n")
    temporary.replace(path)


def _parse_sha256sums(text: str, asset_name: str) -> str:
    """从 SHA256SUMS 中提取指定文件名的 sha256。"""
    target: str = Path(asset_name).name.lower()
    fallback: str = ""
    for raw_line in str(text or "").splitlines():
        line: str = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts: list[str] = line.replace("\t", " ").split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts[0].strip().lower(), parts[1].strip()
        if name.startswith("*"):
            name = name[1:]
        if name.lower() == target:
            return digest
        if not fallback and re.fullmatch(r"[0-9a-f]{64}", digest):
            fallback = digest
    return fallback


def _parse_md5sums(text: str, asset_name: str) -> str:
    """从平台 md5 文件中提取指定文件名的 MD5。"""
    target: str = Path(asset_name).name.lower()
    fallback: str = ""
    for raw_line in str(text or "").splitlines():
        line: str = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts: list[str] = line.replace("\t", " ").split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts[0].strip().lower(), parts[1].strip()
        if name.startswith("*"):
            name = name[1:]
        if name.lower() == target:
            return digest
        if not fallback and re.fullmatch(r"[0-9a-f]{32}", digest):
            fallback = digest
    return fallback


class UpdateService:
    """线程安全的更新检查/下载/准备/安装服务。"""

    def __init__(self, request_exit: Any | None = None) -> None:
        self._lock: threading.RLock = threading.RLock()
        self._cancel: threading.Event = threading.Event()
        self._shutdown: bool = False
        self._check_thread: threading.Thread | None = None
        self._download_thread: threading.Thread | None = None
        self._sessions: list[requests.Session] = []
        self._download_session: requests.Session | None = None
        self._release: ReleaseInfo | None = None
        self._prepared: PreparedUpdate | None = None
        self._state: dict[str, Any] = _idle_state()
        self._request_exit = request_exit
        try:
            self._installer: PlatformInstaller | None = get_platform_installer()
        except Exception:
            self._installer = None
        self._state["can_install"] = bool(
            self._installer is not None and self._installer.is_supported()
        )

    @property
    def installer(self) -> PlatformInstaller | None:
        """返回平台安装器。"""
        return self._installer

    def snapshot(self) -> dict[str, Any]:
        """返回状态快照。"""
        with self._lock:
            return copy.deepcopy(self._state)

    def _set_state(self, **fields: Any) -> dict[str, Any]:
        with self._lock:
            self._state.update(fields)
            return copy.deepcopy(self._state)

    # ------------------------------------------------------------------ 检查
    def check(self, force: bool = False) -> dict[str, Any]:
        """启动一次后台版本检查。"""
        if not bool(load_config().get("update_notice", True)):
            return self._set_state(status="disabled", error="")
        with self._lock:
            if self._shutdown:
                return copy.deepcopy(self._state)
            status: str = str(self._state.get("status") or "idle")
            if not force and status in (
                "checking",
                "downloading",
                "preparing",
                "ready",
                "available",
            ):
                return copy.deepcopy(self._state)
            self._cancel.clear()
            self._state.update(
                {
                    "status": "checking",
                    "progress": 0,
                    "error": "",
                    "latest": "",
                    "source": "",
                    "notes": "",
                    "asset_name": "",
                    "asset_size": 0,
                    "prepared": False,
                    "download_path": "",
                    "staging_path": "",
                    "release_url": "",
                }
            )
            thread = threading.Thread(
                target=self._check_worker, name="UpdateCheck", daemon=True
            )
            self._check_thread = thread
            snapshot: dict[str, Any] = copy.deepcopy(self._state)
        thread.start()
        return snapshot

    def _check_worker(self) -> None:
        """并行请求两个 release 源，首个成功响应生效。"""
        if self._installer is None:
            self._set_state(status="error", error="当前平台不支持自动更新")
            return
        sessions: list[requests.Session] = []
        results: list[ReleaseInfo] = []
        lock: threading.Lock = threading.Lock()
        done: threading.Event = threading.Event()
        remaining: list[int] = [2]

        def worker(name: str, url: str, headers: dict[str, str]) -> None:
            session: requests.Session = requests.Session()
            with lock:
                sessions.append(session)
            with self._lock:
                self._sessions.append(session)
            try:
                response = session.get(url, headers=headers, timeout=_HTTP_TIMEOUT)
                response.raise_for_status()
                release: ReleaseInfo | None = _normalize_release(response.json(), name)
                with lock:
                    if release is not None and not done.is_set():
                        results.append(release)
                        done.set()
            except Exception as exc:
                _LOGGER.info("更新检查源 %s 不可用: %s", name, exc)
            finally:
                with lock:
                    remaining[0] -= 1
                    if remaining[0] <= 0:
                        done.set()
                try:
                    session.close()
                except Exception:
                    pass
                with self._lock:
                    try:
                        self._sessions.remove(session)
                    except ValueError:
                        pass

        headers_github: dict[str, str] = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        headers_gitcode: dict[str, str] = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        }
        threads: list[threading.Thread] = [
            threading.Thread(
                target=worker,
                args=("github", _GITHUB_API, headers_github),
                name="UpdateCheckGitHub",
                daemon=True,
            ),
            threading.Thread(
                target=worker,
                args=("gitcode", _GITCODE_API, headers_gitcode),
                name="UpdateCheckGitCode",
                daemon=True,
            ),
        ]
        for thread in threads:
            thread.start()
        done.wait(_RACE_WAIT_SECONDS)
        with lock:
            active_sessions = list(sessions)
        for session in active_sessions:
            try:
                session.close()
            except Exception:
                pass
        if self._cancel.is_set() or self._shutdown:
            return
        release: ReleaseInfo | None = results[0] if results else None
        if release is None:
            self._set_state(status="none", error="")
            return
        if not _is_newer(release.tag, APP_VERSION):
            self._set_state(status="none", latest=release.tag)
            return
        platform: str
        arch: str
        try:
            platform, arch = self._installer.platform_tags()
        except Exception:
            platform, arch = "", ""
        asset: ReleaseAsset | None = select_auto_asset(
            release.assets,
            platform=platform,
            arch=arch,
            version=release.version,
            dev_build=bool(DEV_BUILD),
        )
        if asset is None:
            self._set_state(status="none", latest=release.tag)
            return
        self._release = release
        self._set_state(
            status="available",
            latest=release.tag,
            source=release.source,
            notes=release.notes,
            release_url=release.release_url,
            asset_name=asset.name,
            asset_size=asset.size,
            can_install=bool(self._installer.is_supported()),
            error="",
        )

    # ------------------------------------------------------------------ 下载
    def download(self) -> dict[str, Any]:
        """下载更新 zip，校验 SHA-256，解压/校验到 staging。"""
        with self._lock:
            if self._shutdown:
                return copy.deepcopy(self._state)
            if self._state.get("status") != "available" or self._release is None:
                return copy.deepcopy(self._state)
            if self._installer is None:
                self._state.update(status="error", error="当前平台不支持自动更新")
                return copy.deepcopy(self._state)
            self._cancel.clear()
            self._state.update(status="downloading", progress=0, error="")
            thread = threading.Thread(
                target=self._download_worker,
                name="UpdateDownload",
                daemon=True,
            )
            self._download_thread = thread
            snapshot: dict[str, Any] = copy.deepcopy(self._state)
        thread.start()
        return snapshot

    def _download_worker(self) -> None:
        """下载、校验并在后台完成 staging。"""
        release: ReleaseInfo | None = self._release
        if release is None or self._installer is None:
            return
        platform, arch = self._installer.platform_tags()
        asset: ReleaseAsset | None = select_auto_asset(
            release.assets,
            platform=platform,
            arch=arch,
            version=release.version,
            dev_build=bool(DEV_BUILD),
        )
        if asset is None:
            self._set_state(status="error", error="没有匹配当前平台的更新 zip")
            return
        version: str = str(release.tag or "")
        download_dir: Path = _download_dir()
        download_dir.mkdir(parents=True, exist_ok=True)
        target: Path = download_dir / _safe_asset_name(asset.name)
        part: Path = target.with_suffix(target.suffix + ".part")
        session: requests.Session = requests.Session()
        with self._lock:
            self._download_session = session
        sha = hashlib.sha256()
        md5 = hashlib.md5()
        received: int = 0
        try:
            with session.get(
                asset.url,
                headers={"User-Agent": _USER_AGENT},
                timeout=(10.0, 60.0),
                stream=True,
            ) as response:
                response.raise_for_status()
                total: int = int(
                    response.headers.get("Content-Length") or asset.size or 0
                )
                with part.open("wb") as fp:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if self._cancel.is_set() or self._shutdown:
                            raise RuntimeError("下载已取消")
                        if not chunk:
                            continue
                        received += len(chunk)
                        if received > _MAX_ASSET_BYTES:
                            raise RuntimeError("更新文件过大")
                        fp.write(chunk)
                        sha.update(chunk)
                        md5.update(chunk)
                        self._set_state(
                            progress=min(99, int(received * 100 / total))
                            if total
                            else 0
                        )
            actual_digest: str = sha.hexdigest().lower()
            expected_digest: str = ""
            if str(asset.digest).lower().startswith("sha256:"):
                expected_digest = str(asset.digest).split(":", 1)[1].strip().lower()
            sums_asset: ReleaseAsset | None = next(
                (
                    item
                    for item in release.assets
                    if item.name.lower() == "sha256sums"
                ),
                None,
            )
            if sums_asset is not None and _download_url_allowed(sums_asset.url):
                sums_response = session.get(
                    sums_asset.url,
                    headers={"User-Agent": _USER_AGENT},
                    timeout=_HTTP_TIMEOUT,
                )
                sums_response.raise_for_status()
                expected_digest = _parse_sha256sums(
                    sums_response.text, asset.name
                ) or expected_digest
            if expected_digest:
                if actual_digest != expected_digest:
                    raise RuntimeError("更新文件 SHA-256 校验失败")
            else:
                # sha256 缺失时，使用与平台/版本对应的 md5 文件。
                md5_asset: ReleaseAsset | None = select_md5_asset(
                    release.assets,
                    platform=platform,
                    arch=arch,
                    version=release.version,
                    dev_build=bool(DEV_BUILD),
                )
                expected_md5: str = ""
                if md5_asset is not None and _download_url_allowed(md5_asset.url):
                    md5_response = session.get(
                        md5_asset.url,
                        headers={"User-Agent": _USER_AGENT},
                        timeout=_HTTP_TIMEOUT,
                    )
                    md5_response.raise_for_status()
                    expected_md5 = _parse_md5sums(md5_response.text, asset.name)
                if not expected_md5:
                    raise RuntimeError(
                        "发布方未提供 SHA256SUMS/sha256 摘要，"
                        "也没有匹配的 hwklr4bjtu-<platform>-<arch>-md5-v*.txt"
                    )
                if md5.hexdigest().lower() != expected_md5:
                    raise RuntimeError("更新文件 MD5 校验失败")
            part.replace(target)
            self._set_state(status="preparing", progress=100, error="")
            staging: Path = _staging_dir() / _safe_asset_name(version)
            if staging.exists():
                import shutil

                shutil.rmtree(staging, ignore_errors=True)
            self._installer.extract(target, staging)
            # 发布 ZIP 常带一层产物目录；先压平，确保 BUILD_INFO 与入口在根目录。
            self._installer.normalize_staging(staging)
            entry: Path = self._installer.validate(staging, version)
            previous: str = self._installer.current_version()
            prepared = PreparedUpdate(
                version=version,
                tag=version,
                staged_dir=staging,
                archive=target,
                entry=entry,
                previous=previous,
            )
            self._prepared = prepared
            _write_json_atomic(
                _pending_file(),
                {
                    "version": version,
                    "staged_dir": str(staging),
                    "archive": str(target),
                    "attempts": 0,
                    "created_at": time.time(),
                },
            )
            self._set_state(
                status="ready",
                progress=100,
                prepared=True,
                download_path=str(target),
                staging_path=str(staging),
                pending=True,
                error="",
            )
        except Exception as exc:
            try:
                part.unlink()
            except OSError:
                pass
            if self._cancel.is_set() or self._shutdown:
                return
            _LOGGER.warning("更新准备失败: %s", exc)
            self._set_state(status="error", error=str(exc))
        finally:
            with self._lock:
                self._download_session = None
            try:
                session.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ 安装
    def install(self, restart: bool = True) -> dict[str, Any]:
        """激活 staging 版本并写 current.json；restart 时启动 launcher。"""
        if self._installer is None or not self._installer.is_supported():
            return {
                "ok": False,
                "error": "当前运行方式不支持自动安装；请手动下载更新包。",
                "pending": False,
            }
        prepared: PreparedUpdate | None = self._prepared
        if prepared is None or self.snapshot().get("status") != "ready":
            return {"ok": False, "error": "更新尚未准备完成", "pending": False}
        try:
            version_dir: Path = self._installer.activate(
                prepared.staged_dir, prepared.version
            )
            self._installer.write_current(prepared.version, prepared.previous)
            self._installer.cleanup_old_versions()
            if restart:
                started: bool = self._installer.restart(
                    prepared.version, notice="ok"
                )
                if not started:
                    self._installer.rollback()
                    return {
                        "ok": False,
                        "error": "无法启动新版本，已回滚到上一版本",
                        "pending": True,
                    }
                self._schedule_exit()
            try:
                _pending_file().unlink()
            except OSError:
                pass
            self._prepared = None
            self._set_state(status="installed", pending=False)
            return {"ok": True, "error": "", "pending": False}
        except (InstallerError, OSError) as exc:
            _LOGGER.warning("安装更新失败: %s", exc)
            return {"ok": False, "error": str(exc), "pending": True}

    def _schedule_exit(self) -> None:
        """桥接响应返回后关闭窗口。"""
        callback = self._request_exit
        if not callable(callback):
            return
        timer = threading.Timer(0.6, callback)
        timer.daemon = True
        timer.start()

    def rollback(self) -> dict[str, Any]:
        """手动回滚到 previous。"""
        if self._installer is None:
            return {"ok": False, "error": "当前平台不支持自动更新"}
        version: str | None = self._installer.rollback()
        if not version:
            return {"ok": False, "error": "没有可回滚的版本"}
        return {"ok": True, "version": version, "error": ""}

    def shutdown(self) -> None:
        """取消后台任务并关闭连接。"""
        self._shutdown = True
        self._cancel.set()
        with self._lock:
            sessions = list(self._sessions)
            download_session = self._download_session
        for session in sessions + ([download_session] if download_session else []):
            try:
                session.close()
            except Exception:
                pass
        for thread in (self._check_thread, self._download_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=0.5)


def bootstrap_current_version() -> bool:
    """若 current.json 指向另一个已安装版本，则启动它并返回 True。

    这让任意版本目录中的旧程序也能作为轻量 bootstrap 使用；新版
    launcher 接入后仍可保留此逻辑作为兜底。
    """
    if not getattr(sys, "frozen", False):
        return False
    try:
        installer = get_platform_installer()
    except Exception:
        return False
    current: str = installer.current_version()
    if not current:
        return False
    if parse_version(current) == parse_version(APP_VERSION):
        return False
    target: Path = installer.version_dir(current)
    if not target.exists():
        return False
    if installer.restart(current, notice=""):
        return True
    installer.rollback()
    return False


def cleanup_incomplete_update() -> None:
    """启动时清理未完成 staging（不自动应用更新）。"""
    pending: dict[str, Any] | None = _read_json(_pending_file())
    if pending is None:
        return
    try:
        installer = get_platform_installer()
    except Exception:
        return
    current: str = installer.current_version()
    version: str = str(pending.get("version") or "")
    if current and current == version:
        # current 已切换，说明上一次激活成功，只清理 pending。
        try:
            _pending_file().unlink()
        except OSError:
            pass
        return
    staged: Path | None = Path(str(pending.get("staged_dir") or ""))
    try:
        staged.resolve().relative_to(_staging_dir().resolve())
    except (OSError, ValueError):
        staged = None
    if staged is not None:
        import shutil

        shutil.rmtree(staged, ignore_errors=True)
    try:
        _pending_file().unlink()
    except OSError:
        pass
