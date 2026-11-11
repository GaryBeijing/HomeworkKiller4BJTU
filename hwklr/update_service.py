# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-11 10:00
# 最后更新: 2026-11-11 20:00
# 文件名: update_service.py
# 主要用途: 启动时并行检查 GitHub/GitCode 新版本、后台下载 release、生成待安装标记并在下次启动或退出时解压 7z 自解压包/zip。
# 文件版本: 4.4.3
"""自动更新服务。

本模块不依赖 UI：窗口层通过 :class:`UpdateService` 的公开方法查询状态、
开始下载或安装；前端只负责轮询与展示。更新只访问公开的 release API，
不读取 ``auth/`` 下的任何凭据。
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Final

import requests

from hwklr import DEV_BUILD, __version__ as APP_VERSION
from hwklr.config import app_root, load_config

__version__ = "4.4.3"
__author__ = "Gary"
__all__ = [
    "UpdateService",
    "apply_pending_update",
    "is_install_supported",
    "parse_version",
    "runtime_layout",
    "select_asset",
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
_HTTP_TIMEOUT: Final[tuple[float, float]] = (5.0, 10.0)
_RACE_WAIT_SECONDS: Final[float] = 12.0
_MAX_NOTES_CHARS: Final[int] = 20_000
_MAX_ASSET_BYTES: Final[int] = 512 * 1024 * 1024
_ALLOWED_SUFFIXES: Final[frozenset[str]] = frozenset({".exe", ".zip"})
_SAFE_NAME: Final[re.Pattern[str]] = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_PROTECTED_NAMES: Final[frozenset[str]] = frozenset(
    {
        "config.json",
        "auth",
        "db",
        "extension",
        "documents",
        "artifacts",
        "updates",
    }
)


def updates_dir() -> Path:
    """返回更新工作目录。

    Returns:
        ``app_root()/updates``。
    """
    return app_root() / "updates"


def _download_dir() -> Path:
    """返回下载目录。"""
    return updates_dir() / "download"


def _pending_file() -> Path:
    """返回待安装标记文件。"""
    return updates_dir() / "pending.json"


def _idle_state() -> dict[str, Any]:
    """返回空闲状态快照。"""
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
        "pending": False,
        "download_path": "",
        "release_url": "",
    }


def parse_version(text: Any) -> tuple[int, int, int] | None:
    """解析版本号前三段，忽略 ``v`` 前缀与第四段构建号。

    Args:
        text: ``v4.4.3`` / ``4.4.2.9999`` 等。

    Returns:
        ``(major, minor, patch)``；格式不合法时返回 ``None``。
    """
    match: re.Match[str] | None = re.match(
        r"^[vV]?(\d+)\.(\d+)\.(\d+)", str(text or "").strip()
    )
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _is_newer(remote: Any, current: Any) -> bool:
    """判断远端版本是否高于当前版本。"""
    remote_parts = parse_version(remote)
    current_parts = parse_version(current)
    if remote_parts is None or current_parts is None:
        return False
    return remote_parts > current_parts


def runtime_layout() -> str:
    """返回当前运行布局：``source`` / ``onedir`` / ``onefile``。"""
    if not getattr(sys, "frozen", False):
        return "source"
    executable: Path = Path(sys.executable).resolve()
    if (executable.parent / "_internal").is_dir():
        return "onedir"
    return "onefile"


def is_install_supported(layout: str, asset_name: str) -> bool:
    """判断当前布局是否支持自动解压安装。

    发行版的单文件 ``.exe`` 一定是 7z 自解压包，``.zip`` 是普通压缩包；
    两者都通过“解压到程序目录”安装，不再直接替换 exe。

    Args:
        layout: :func:`runtime_layout` 的结果。
        asset_name: release 资产文件名。

    Returns:
        支持返回 ``True``。
    """
    if layout == "source":
        return False
    return Path(str(asset_name or "")).suffix.lower() in _ALLOWED_SUFFIXES


def _install_mode(path: Path) -> str:
    """返回更新包的安装方式：``sfx`` 或 ``zip``。

    Args:
        path: 已下载的更新文件。

    Returns:
        ``"zip"`` 或 ``"sfx"``。
    """
    return "zip" if Path(path).suffix.lower() == ".zip" else "sfx"


def _normalize_release(payload: Any, source: str) -> dict[str, Any] | None:
    """把 GitHub/GitCode 的 release JSON 归并为统一结构。

    Args:
        payload: API 返回的 JSON。
        source: ``github`` 或 ``gitcode``。

    Returns:
        统一 release 字典；缺少 tag 时返回 ``None``。
    """
    if not isinstance(payload, dict):
        return None
    tag: str = str(payload.get("tag_name") or payload.get("name") or "").strip()
    if not tag:
        return None
    assets: list[dict[str, Any]] = []
    raw_assets: Any = payload.get("assets")
    if isinstance(raw_assets, list):
        for item in raw_assets:
            if not isinstance(item, dict):
                continue
            # GitCode 同时返回源码归档（type=source），不能当作可执行更新包。
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
                {
                    "name": name,
                    "url": url,
                    "size": max(0, size),
                    "digest": str(item.get("digest") or ""),
                }
            )
    return {
        "tag": tag,
        "source": source,
        "notes": str(payload.get("body") or "")[:_MAX_NOTES_CHARS],
        "release_url": str(payload.get("html_url") or ""),
        "assets": assets,
    }


def _download_url_allowed(url: str) -> bool:
    """检查下载地址是否为受信任的 HTTPS 主机。"""
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
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


def _safe_asset_name(name: str) -> str:
    """把 release 资产名转换为安全的本地文件名。"""
    base: str = Path(str(name or "")).name
    cleaned: str = _SAFE_NAME.sub("_", base).strip(" .")
    return cleaned or "update.bin"


def select_asset(
    assets: list[dict[str, Any]],
    *,
    dev_build: bool = DEV_BUILD,
    layout: str | None = None,
) -> dict[str, Any] | None:
    """选择与当前构建类型、运行布局最匹配的资产。

    Args:
        assets: 归并后的资产列表。
        dev_build: 当前是否为开发构建。
        layout: 运行布局；``None`` 时自动探测。

    Returns:
        选中的资产字典；没有可用资产时返回 ``None``。
    """
    layout = layout or runtime_layout()
    candidates: list[dict[str, Any]] = [
        item
        for item in assets
        if Path(str(item.get("name") or "")).suffix.lower() in _ALLOWED_SUFFIXES
        and _download_url_allowed(str(item.get("url") or ""))
    ]
    if not candidates:
        return None
    # 优先匹配 -dev 后缀；没有完全匹配时回退到任意可用资产。
    matched: list[dict[str, Any]] = [
        item
        for item in candidates
        if ("-dev" in Path(str(item.get("name") or "")).stem.lower()) == dev_build
    ]
    pool: list[dict[str, Any]] = matched or candidates
    # 新发行格式统一为 7z 自解压 exe；没有 exe 时才回退 zip。
    for item in pool:
        if Path(str(item.get("name") or "")).suffix.lower() == ".exe":
            return item
    return pool[0]


def _read_json(path: Path) -> dict[str, Any] | None:
    """读取 JSON 对象；失败时返回 ``None``。"""
    try:
        with path.open(encoding="utf-8-sig") as fp:
            data: Any = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """原子写入 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp: Path = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
        fp.write("\n")
    temp.replace(path)


def _ps_quote(value: str) -> str:
    """把字符串转换为 PowerShell 单引号字面量。"""
    return "'" + str(value).replace("'", "''") + "'"


def _updater_script(pending: dict[str, Any]) -> str:
    """生成等待旧进程退出后解压更新的 PowerShell 脚本。

    Args:
        pending: ``pending.json`` 内容。

    Returns:
        PowerShell 脚本文本。
    """
    root: Path = app_root().resolve()
    asset: Path = Path(str(pending.get("asset_path") or "")).resolve()
    target: Path = Path(str(pending.get("target") or "")).resolve()
    pending_path: Path = _pending_file().resolve()
    staging: Path = (
        updates_dir()
        / "staging"
        / _safe_asset_name(str(pending.get("tag") or "update"))
    ).resolve()
    mode: str = str(pending.get("mode") or _install_mode(asset))
    log_path: Path = updates_dir() / "update.log"
    pid: int = int(pending.get("pid") or 0)
    protected: str = ", ".join(_ps_quote(name) for name in sorted(_PROTECTED_NAMES))
    return f"""$ErrorActionPreference = 'Stop'
$log = {_ps_quote(str(log_path))}
function Write-Log($message) {{
  try {{ Add-Content -LiteralPath $log -Value ('[{{0}}] {{1}}' -f (Get-Date -Format 's'), $message) -Encoding UTF8 }} catch {{ }}
}}
$pidToWait = {pid}
$asset = {_ps_quote(str(asset))}
$target = {_ps_quote(str(target))}
$root = {_ps_quote(str(root))}
$pending = {_ps_quote(str(pending_path))}
$staging = {_ps_quote(str(staging))}
$mode = {_ps_quote(mode)}
$protected = @({protected})
try {{
  Write-Log ('waiting for process ' + $pidToWait)
  if ($pidToWait -gt 0) {{
    try {{ Wait-Process -Id $pidToWait -Timeout 120 -ErrorAction Stop }} catch {{ Write-Log 'process wait timed out or already exited' }}
  }}
  if (-not (Test-Path -LiteralPath $asset)) {{ throw ('asset missing: ' + $asset) }}
  if (Test-Path -LiteralPath $staging) {{ Remove-Item -LiteralPath $staging -Recurse -Force }}
  New-Item -ItemType Directory -Path $staging -Force | Out-Null
  if ($mode -eq 'zip') {{
    Expand-Archive -LiteralPath $asset -DestinationPath $staging -Force
  }} else {{
    # 发行版单文件 exe 是 7z 自解压包。优先用本机 7z.exe 当普通 7z 包解压，
    # 避免 GUI SFX 可能提权后留下当前用户无法读取的文件。
    $sevenZip = ''
    foreach ($candidate in @('C:\\Program Files\\7-Zip\\7z.exe', 'C:\\Program Files (x86)\\7-Zip\\7z.exe')) {{
      if (Test-Path -LiteralPath $candidate) {{ $sevenZip = $candidate; break }}
    }}
    if (-not $sevenZip) {{
      $found7z = Get-Command 7z.exe -ErrorAction SilentlyContinue
      if (-not $found7z) {{ $found7z = Get-Command 7z -ErrorAction SilentlyContinue }}
      if ($found7z) {{ $sevenZip = $found7z.Source }}
    }}
    if ($sevenZip) {{
      Write-Log ('7z extract: ' + $sevenZip)
      & $sevenZip x $asset "-o$staging" -y -aoa | Out-Null
      # 7z 同步执行并校验归档 CRC；非 0 退出码代表解压失败/不完整。
      if ($LASTEXITCODE -ne 0) {{
        throw ('7z extract failed with exit code ' + $LASTEXITCODE)
      }}
    }} else {{
      # 没有 7z.exe 时执行 SFX 自身（推荐发行版使用 7zCon.sfx 控制台模块）。
      try {{
        $arguments = @('-y', ('-o"' + $staging + '"'))
        $proc = Start-Process -FilePath $asset -ArgumentList $arguments -PassThru -WindowStyle Hidden
        $lastCount = -1
        $lastSize = -1
        $stable = 0
        $finished = $false
        $killed = $false
        $deadline = (Get-Date).AddSeconds(180)
        while ((Get-Date) -lt $deadline) {{
          Start-Sleep -Seconds 1
          if ($proc.HasExited) {{ $finished = $true; break }}
          $files = @(Get-ChildItem -LiteralPath $staging -Recurse -File -ErrorAction SilentlyContinue)
          $count = $files.Count
          $size = 0
          if ($count -gt 0) {{ $size = [int64](($files | Measure-Object -Property Length -Sum).Sum) }}
          if ($count -gt 0 -and $count -eq $lastCount -and $size -eq $lastSize) {{
            $stable += 1
            if ($stable -ge 3) {{
              # 数量/大小稳定后再确认所有文件可读（未被写入锁占用）。
              $readable = $true
              foreach ($file in $files) {{
                try {{
                  $stream = [System.IO.File]::Open($file.FullName, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                  $stream.Close()
                }} catch {{
                  $readable = $false
                  break
                }}
              }}
              if ($readable) {{
                $finished = $true
                break
              }}
              $stable = 0
            }}
          }} else {{
            $stable = 0
          }}
          $lastCount = $count
          $lastSize = $size
        }}
        if (-not $finished) {{ throw 'sfx extraction timed out' }}
        if (-not $proc.HasExited) {{
          $killed = $true
          try {{ Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }} catch {{ }}
        }}
        if (-not $killed -and $proc.ExitCode -ne 0) {{
          throw ('sfx exited with code ' + $proc.ExitCode)
        }}
        if ($killed) {{ Write-Log 'sfx process still open; accepted stable extraction' }}
        # 给系统释放 SFX 对已解压文件的句柄，避免随后 Copy-Item 访问被拒绝。
        Start-Sleep -Seconds 2
      }} catch {{
        Write-Log ('sfx start failed: ' + $_.Exception.Message)
      }}
    }}
  }}
  $items = @(Get-ChildItem -LiteralPath $staging -Force -ErrorAction SilentlyContinue)
  if ($items.Count -eq 0) {{ throw 'update extracted no files' }}
  $sourceRoot = $staging
  if ($items.Count -eq 1 -and $items[0].PSIsContainer) {{
    $innerExe = @(Get-ChildItem -LiteralPath $items[0].FullName -Filter *.exe -File -ErrorAction SilentlyContinue)
    if ($innerExe.Count -gt 0) {{ $sourceRoot = $items[0].FullName }}
  }}
  $sourceExe = @(Get-ChildItem -LiteralPath $sourceRoot -Filter *.exe -File -ErrorAction SilentlyContinue)
  if ($sourceExe.Count -eq 0) {{
    $sourceExe = @(Get-ChildItem -LiteralPath $sourceRoot -Recurse -Filter *.exe -File -ErrorAction SilentlyContinue)
  }}
  if ($sourceExe.Count -eq 0) {{ throw 'update package contains no exe' }}
  Get-ChildItem -LiteralPath $sourceRoot -Force | ForEach-Object {{
    if ($protected -contains $_.Name) {{ return }}
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $root $_.Name) -Recurse -Force
  }}
  Get-ChildItem -LiteralPath $root -Recurse -File -Include *.exe,*.dll -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue
  if (-not (Test-Path -LiteralPath $target)) {{
    $found = @(Get-ChildItem -LiteralPath $root -Filter *.exe -File -ErrorAction SilentlyContinue)
    if ($found.Count -gt 0) {{ $target = $found[0].FullName }}
  }}
  if (-not (Test-Path -LiteralPath $target)) {{ throw 'updated exe not found' }}
  if ((Get-Item -LiteralPath $target).Length -le 0) {{ throw 'updated exe is empty' }}
  Unblock-File -LiteralPath $target -ErrorAction SilentlyContinue
  Start-Process -FilePath $target -WorkingDirectory $root
  # 只有启动成功后移除 pending，失败时下次启动可以重试。
  Remove-Item -LiteralPath $pending -Force -ErrorAction SilentlyContinue
  Write-Log 'update applied'
}} catch {{
  Write-Log ('update failed: ' + $_.Exception.Message)
}}
"""


class UpdateService:
    """线程安全的更新检查/下载/安装服务。"""

    def __init__(self, request_exit: Any | None = None) -> None:
        """初始化服务。

        Args:
            request_exit: 安装后关闭窗口的回调；``None`` 时仅写 pending。
        """
        self._lock: threading.RLock = threading.RLock()
        self._cancel: threading.Event = threading.Event()
        self._shutdown: bool = False
        self._check_thread: threading.Thread | None = None
        self._download_thread: threading.Thread | None = None
        self._sessions: list[requests.Session] = []
        self._download_session: requests.Session | None = None
        self._state: dict[str, Any] = _idle_state()
        self._release: dict[str, Any] | None = None
        self._request_exit = request_exit

    # ------------------------------------------------------------------ 状态
    def snapshot(self) -> dict[str, Any]:
        """返回状态快照副本。"""
        with self._lock:
            return copy.deepcopy(self._state)

    def _set_state(self, **fields: Any) -> dict[str, Any]:
        """在锁内更新状态并返回快照。"""
        with self._lock:
            self._state.update(fields)
            return copy.deepcopy(self._state)

    # ------------------------------------------------------------------ 检查
    def check(self, force: bool = False) -> dict[str, Any]:
        """启动一次后台版本检查。

        Args:
            force: 忽略“检查中/已可用”的防重入限制。

        Returns:
            当前状态快照。
        """
        enabled: bool = bool(load_config().get("update_notice", True))
        if not enabled:
            return self._set_state(status="disabled", error="")
        with self._lock:
            if self._shutdown:
                return copy.deepcopy(self._state)
            status: str = str(self._state.get("status") or "idle")
            if not force and status in ("checking", "downloading", "ready", "available"):
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
                    "can_install": False,
                    "download_path": "",
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
        sessions: list[requests.Session] = []
        results: list[tuple[str, dict[str, Any] | None]] = []
        lock: threading.Lock = threading.Lock()
        done: threading.Event = threading.Event()
        remaining: list[int] = [2]

        def worker(name: str, url: str, headers: dict[str, str]) -> None:
            session: requests.Session = requests.Session()
            with lock:
                sessions.append(session)
            with self._lock:
                self._sessions.append(session)
            payload: Any = None
            try:
                response = session.get(url, headers=headers, timeout=_HTTP_TIMEOUT)
                response.raise_for_status()
                payload = response.json()
                release: dict[str, Any] | None = _normalize_release(payload, name)
                with lock:
                    if release is not None and not done.is_set():
                        results.append((name, release))
                        done.set()
            except Exception as exc:  # 网络/解析失败由另一个源兜底
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

        github_headers: dict[str, str] = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        gitcode_headers: dict[str, str] = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        }
        threads: list[threading.Thread] = [
            threading.Thread(
                target=worker,
                args=("github", _GITHUB_API, github_headers),
                name="UpdateCheckGitHub",
                daemon=True,
            ),
            threading.Thread(
                target=worker,
                args=("gitcode", _GITCODE_API, gitcode_headers),
                name="UpdateCheckGitCode",
                daemon=True,
            ),
        ]
        for thread in threads:
            thread.start()
        done.wait(_RACE_WAIT_SECONDS)
        # 首个响应后终止另一方：关闭两个 Session（尽力中断仍在途的请求）。
        with lock:
            active_sessions = list(sessions)
        for session in active_sessions:
            try:
                session.close()
            except Exception:
                pass
        if self._cancel.is_set() or self._shutdown:
            return
        release: dict[str, Any] | None = results[0][1] if results else None
        if release is None:
            self._set_state(status="none", error="")
            return
        latest: str = str(release.get("tag") or "")
        if not _is_newer(latest, APP_VERSION):
            self._set_state(status="none", latest=latest)
            return
        asset: dict[str, Any] | None = select_asset(
            list(release.get("assets") or []),
            dev_build=bool(DEV_BUILD),
            layout=runtime_layout(),
        )
        if asset is None:
            self._set_state(status="none", latest=latest)
            return
        can_install: bool = is_install_supported(
            runtime_layout(), str(asset.get("name") or "")
        )
        self._release = release
        self._set_state(
            status="available",
            latest=latest,
            source=str(release.get("source") or ""),
            notes=str(release.get("notes") or ""),
            release_url=str(release.get("release_url") or ""),
            asset_name=str(asset.get("name") or ""),
            asset_size=int(asset.get("size") or 0),
            can_install=can_install,
            error="",
        )

    # ------------------------------------------------------------------ 下载
    def download(self) -> dict[str, Any]:
        """启动后台下载已选中的 release 资产。"""
        with self._lock:
            if self._shutdown:
                return copy.deepcopy(self._state)
            if self._state.get("status") != "available":
                return copy.deepcopy(self._state)
            release: dict[str, Any] | None = self._release
            asset: dict[str, Any] | None = select_asset(
                list((release or {}).get("assets") or []),
                dev_build=bool(DEV_BUILD),
                layout=runtime_layout(),
            )
            if asset is None:
                self._state.update(status="error", error="没有可下载的更新文件")
                return copy.deepcopy(self._state)
            self._cancel.clear()
            self._state.update(
                status="downloading",
                progress=0,
                error="",
                asset_name=str(asset.get("name") or ""),
                asset_size=int(asset.get("size") or 0),
            )
            thread = threading.Thread(
                target=self._download_worker,
                args=(dict(asset),),
                name="UpdateDownload",
                daemon=True,
            )
            self._download_thread = thread
            snapshot: dict[str, Any] = copy.deepcopy(self._state)
        thread.start()
        return snapshot

    def _download_worker(self, asset: dict[str, Any]) -> None:
        """下载资产到 ``updates/download``，边下边写进度。"""
        url: str = str(asset.get("url") or "")
        if not _download_url_allowed(url):
            self._set_state(status="error", error="更新下载地址不受信任")
            return
        name: str = _safe_asset_name(str(asset.get("name") or "update.bin"))
        target_dir: Path = _download_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        final_path: Path = target_dir / name
        part_path: Path = final_path.with_suffix(final_path.suffix + ".part")
        expected_size: int = int(asset.get("size") or 0)
        if expected_size > _MAX_ASSET_BYTES:
            self._set_state(status="error", error="更新文件过大，已取消下载")
            return
        session: requests.Session = requests.Session()
        with self._lock:
            self._download_session = session
        digest = hashlib.sha256()
        received: int = 0
        try:
            with session.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=(10.0, 60.0),
                stream=True,
            ) as response:
                response.raise_for_status()
                total: int = int(
                    response.headers.get("Content-Length") or expected_size or 0
                )
                with part_path.open("wb") as fp:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if self._cancel.is_set() or self._shutdown:
                            raise RuntimeError("下载已取消")
                        if not chunk:
                            continue
                        received += len(chunk)
                        if received > _MAX_ASSET_BYTES:
                            raise RuntimeError("更新文件过大，已取消下载")
                        fp.write(chunk)
                        digest.update(chunk)
                        progress: int = (
                            min(99, int(received * 100 / total)) if total else 0
                        )
                        self._set_state(progress=progress)
            expected_digest: str = str(asset.get("digest") or "")
            if expected_digest.lower().startswith("sha256:"):
                actual: str = digest.hexdigest().lower()
                if actual != expected_digest.split(":", 1)[1].strip().lower():
                    raise RuntimeError("更新文件校验失败，请重试")
            part_path.replace(final_path)
            self._set_state(
                status="ready",
                progress=100,
                download_path=str(final_path),
                error="",
            )
        except Exception as exc:
            try:
                part_path.unlink()
            except OSError:
                pass
            if self._cancel.is_set() or self._shutdown:
                return
            _LOGGER.warning("更新下载失败: %s", exc)
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
        """写入待安装标记；``restart`` 为真时启动解压脚本并关闭程序。

        Returns:
            ``{"ok": bool, "error": str, "pending": bool}``。
        """
        if not getattr(sys, "frozen", False):
            return {
                "ok": False,
                "error": "当前为源码运行，无法自动安装更新；请手动下载更新包。",
                "pending": False,
            }
        with self._lock:
            status: str = str(self._state.get("status") or "")
            download_path: str = str(self._state.get("download_path") or "")
            tag: str = str(self._state.get("latest") or "")
        if status != "ready" or not download_path:
            return {"ok": False, "error": "更新尚未下载完成", "pending": False}
        asset_path = Path(download_path)
        try:
            asset_path.resolve().relative_to(updates_dir().resolve())
        except (OSError, ValueError):
            return {"ok": False, "error": "更新文件路径不合法", "pending": False}
        if not asset_path.is_file():
            return {"ok": False, "error": "更新文件不存在", "pending": False}
        if not is_install_supported(runtime_layout(), asset_path.name):
            return {
                "ok": False,
                "error": "当前运行方式不支持自动安装，请手动安装更新包",
                "pending": False,
            }
        pending: dict[str, Any] = {
            "asset_path": str(asset_path.resolve()),
            "asset_name": asset_path.name,
            "target": str(Path(sys.executable).resolve()),
            "tag": tag,
            "mode": _install_mode(asset_path),
            "attempts": 0,
            "pid": os.getpid(),
            "created_at": time.time(),
        }
        try:
            _write_json_atomic(_pending_file(), pending)
        except OSError as exc:
            return {"ok": False, "error": "写入待安装标记失败：%s" % exc, "pending": False}
        self._set_state(pending=True)
        if not restart:
            return {"ok": True, "error": "", "pending": True}
        if not self._spawn_updater(pending):
            return {"ok": False, "error": "无法启动更新脚本", "pending": True}
        self._schedule_exit()
        return {"ok": True, "error": "", "pending": True}

    def _schedule_exit(self) -> None:
        """在桥接响应返回后关闭窗口。"""
        callback = self._request_exit
        if not callable(callback):
            return
        timer = threading.Timer(0.6, callback)
        timer.daemon = True
        timer.start()

    # ------------------------------------------------------------------ 生命周期
    def shutdown(self) -> None:
        """取消后台任务并关闭网络连接。"""
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


def _batch_updater_script(pending: dict[str, Any]) -> str:
    """生成 cmd.exe 更新脚本（PowerShell 被策略禁用时的回退）。

    Args:
        pending: ``pending.json`` 内容。

    Returns:
        ``.cmd`` 文件内容（使用 CRLF）。
    """
    root: Path = app_root().resolve()
    asset: Path = Path(str(pending.get("asset_path") or "")).resolve()
    target: Path = Path(str(pending.get("target") or "")).resolve()
    pending_path: Path = _pending_file().resolve()
    staging: Path = (
        updates_dir()
        / "staging"
        / _safe_asset_name(str(pending.get("tag") or "update"))
    ).resolve()
    mode: str = str(pending.get("mode") or _install_mode(asset))
    pid: int = int(pending.get("pid") or 0)

    def value(text: Any) -> str:
        # 批处理中 % 需要写成 %% 才是字面量。
        return str(text).replace("%", "%%")

    protected_dirs: str = " ".join(
        name for name in sorted(_PROTECTED_NAMES) if name != "config.json"
    )
    script: str = f"""@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "LOG=%~dp0update.log"
set "ASSET={value(asset)}"
set "TARGET={value(target)}"
set "ROOT={value(root)}"
set "PENDING={value(pending_path)}"
set "STAGING={value(staging)}"
set "MODE={value(mode)}"
set "PID={pid}"
>>"%LOG%" echo [%DATE% %TIME%] waiting for process %PID%
if "%PID%"=="0" goto afterwait
:waitloop
tasklist /FI "PID eq %PID%" 2>nul | findstr /C:"%PID%" >nul
if errorlevel 1 goto afterwait
ping -n 2 127.0.0.1 >nul
goto waitloop
:afterwait
if not exist "%ASSET%" goto fail
if exist "%STAGING%" rmdir /s /q "%STAGING%"
mkdir "%STAGING%" >nul 2>&1
if /I "%MODE%"=="zip" goto extractzip
set "SEVENZIP="
if exist "C:\\Program Files\\7-Zip\\7z.exe" set "SEVENZIP=C:\\Program Files\\7-Zip\\7z.exe"
if not defined SEVENZIP if exist "C:\\Program Files (x86)\\7-Zip\\7z.exe" set "SEVENZIP=C:\\Program Files (x86)\\7-Zip\\7z.exe"
if defined SEVENZIP goto extract7z
"%ASSET%" -y "-o%STAGING%" >>"%LOG%" 2>&1
if errorlevel 1 goto fail
goto extracted
:extract7z
"%SEVENZIP%" x "%ASSET%" "-o%STAGING%" -y -aoa >>"%LOG%" 2>&1
if errorlevel 1 goto fail
goto extracted
:extractzip
tar -xf "%ASSET%" -C "%STAGING%" >>"%LOG%" 2>&1
if errorlevel 1 goto fail
:extracted
set "SOURCE=%STAGING%"
set "DIRCOUNT=0"
set "FILECOUNT=0"
set "ONLYDIR="
for /d %%D in ("%STAGING%\\*") do (
  set /a DIRCOUNT+=1
  set "ONLYDIR=%%D"
)
for /f "delims=" %%F in ('dir /b /a-d "%STAGING%" 2^>nul') do set /a FILECOUNT+=1
if not "%DIRCOUNT%"=="1" goto copydata
if not "%FILECOUNT%"=="0" goto copydata
if not exist "%ONLYDIR%\\*.exe" goto copydata
set "SOURCE=%ONLYDIR%"
:copydata
robocopy "%SOURCE%" "%ROOT%" /E /XF config.json /XD {protected_dirs} /R:2 /W:1 /NFL /NDL /NJH /NJS >>"%LOG%" 2>&1
if errorlevel 8 goto fail
if exist "%TARGET%" goto targetok
set "TARGET="
for /f "delims=" %%F in ('dir /b /a-d "%ROOT%\\*.exe" 2^>nul') do if not defined TARGET set "TARGET=%ROOT%\\%%F"
:targetok
if not exist "%TARGET%" goto fail
start "" "%TARGET%"
>>"%LOG%" echo [%DATE% %TIME%] start_errorlevel=%errorlevel%
del /q "%PENDING%" >nul 2>&1
>>"%LOG%" echo [%DATE% %TIME%] update applied
exit /b 0
:fail
>>"%LOG%" echo [%DATE% %TIME%] update failed
exit /b 1
"""
    return script.replace("\n", "\r\n")


def _write_batch_script(path: Path, pending: dict[str, Any]) -> None:
    """以系统 ANSI 编码写入 .cmd，兼容中文路径。"""
    text: str = _batch_updater_script(pending)
    try:
        data: bytes = text.encode("mbcs")
    except (LookupError, UnicodeEncodeError):
        data = text.encode("utf-8")
    path.write_bytes(data)


def _probe_powershell() -> bool:
    """验证 PowerShell 能否通过 -File 执行脚本（含执行策略/AppLocker）。"""
    probe: Path = updates_dir() / "probe.ps1"
    marker: Path = updates_dir() / "probe.ok"
    try:
        updates_dir().mkdir(parents=True, exist_ok=True)
        try:
            marker.unlink()
        except OSError:
            pass
        probe.write_text(
            "Set-Content -LiteralPath %s -Value 'ok' -Encoding UTF8\n"
            % _ps_quote(str(marker)),
            encoding="utf-8-sig",
        )
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(probe),
            ],
            cwd=str(app_root()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        )
        return completed.returncode == 0 and marker.is_file()
    except Exception:
        _LOGGER.info("PowerShell 更新脚本不可用，将尝试 cmd 回退", exc_info=True)
        return False
    finally:
        for path in (probe, marker):
            try:
                path.unlink()
            except OSError:
                pass


def _probe_cmd() -> bool:
    """验证 cmd.exe 能否执行本目录下的 .cmd 文件。"""
    probe: Path = updates_dir() / "probe.cmd"
    try:
        updates_dir().mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"@echo off\r\nexit /b 0\r\n")
        completed = subprocess.run(
            ["cmd.exe", "/c", str(probe)],
            cwd=str(app_root()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        )
        return completed.returncode == 0
    except Exception:
        _LOGGER.info("cmd 更新脚本不可用", exc_info=True)
        return False
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def _launch_detached(command: list[str]) -> bool:
    """以脱离父进程的方式启动更新脚本。

    Args:
        command: 完整命令行。

    Returns:
        成功创建进程返回 ``True``。
    """
    flags: int = 0
    flags |= int(getattr(subprocess, "DETACHED_PROCESS", 0))
    flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        subprocess.Popen(
            command,
            cwd=str(app_root()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
    except Exception:
        _LOGGER.exception("启动更新脚本失败: %s", command[0])
        return False
    return True


def _spawn_updater(pending: dict[str, Any]) -> bool:
    """优先用 PowerShell，被策略禁用时回退到 cmd.exe 更新脚本。

    Args:
        pending: 待安装标记。

    Returns:
        成功启动任一脚本返回 ``True``。
    """
    if sys.platform != "win32":
        _LOGGER.warning("自动安装仅支持 Windows")
        return False
    try:
        updates_dir().mkdir(parents=True, exist_ok=True)
    except OSError:
        _LOGGER.exception("创建更新目录失败")
        return False
    if _probe_powershell():
        script_path: Path = updates_dir() / "apply_update.ps1"
        try:
            # UTF-8 BOM 让 Windows PowerShell 正确读取中文路径。
            script_path.write_text(_updater_script(pending), encoding="utf-8-sig")
        except OSError:
            _LOGGER.exception("写入 PowerShell 更新脚本失败")
        else:
            if _launch_detached(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script_path),
                ]
            ):
                return True
            _LOGGER.warning("PowerShell 更新脚本启动失败，尝试 cmd 回退")
    if _probe_cmd():
        script_path = updates_dir() / "apply_update.cmd"
        try:
            _write_batch_script(script_path, pending)
        except OSError:
            _LOGGER.exception("写入 cmd 更新脚本失败")
        else:
            if _launch_detached(["cmd.exe", "/c", str(script_path)]):
                return True
    _LOGGER.error("PowerShell 与 cmd 更新脚本均不可用")
    return False


def apply_pending_update() -> bool:
    """启动时应用上一次“稍后安装”的更新。

    Returns:
        已启动更新脚本时返回 ``True``，调用方应立即退出进程。
    """
    if not getattr(sys, "frozen", False):
        return False
    pending: dict[str, Any] | None = _read_json(_pending_file())
    if pending is None:
        return False
    asset_path: Path = Path(str(pending.get("asset_path") or ""))
    try:
        asset_path.resolve().relative_to(updates_dir().resolve())
    except (OSError, ValueError):
        _LOGGER.warning("待安装更新路径不合法，已忽略")
        return False
    if not asset_path.is_file():
        _LOGGER.warning("待安装更新文件不存在，已忽略")
        return False
    # 兼容早期没有 mode 字段的 pending.json。
    pending.setdefault("mode", _install_mode(asset_path))
    attempts: int = int(pending.get("attempts") or 0)
    if attempts >= 3:
        _LOGGER.error(
            "待安装更新已连续尝试 %d 次仍未完成，本次跳过自动安装，保留 pending 供手动处理",
            attempts,
        )
        return False
    pending["attempts"] = attempts + 1
    pending["pid"] = os.getpid()
    try:
        _write_json_atomic(_pending_file(), pending)
    except OSError:
        _LOGGER.exception("更新 pending.json 失败")
        return False
    return _spawn_updater(pending)
