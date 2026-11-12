# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-11 21:00
# 最后更新: 2026-11-12 16:50
# 文件名: launcher_windows.py
# 主要用途: Windows 稳定启动器：读取 current.json 与 BUILD_INFO 入口启动 versions/<v>，失败时回退上一版本。
# 文件版本: 4.6.3
"""Windows launcher（仅启动逻辑，不含业务代码）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

__version__ = "4.6.3"
__author__ = "Gary"
__all__ = ["main"]

ENTRY_NAME = "HomeworkKiller4BJTU.exe"


def _install_root() -> Path:
    env_value: str = str(os.environ.get("HWKLR_INSTALL_ROOT") or "").strip()
    if env_value:
        return Path(env_value).resolve()
    executable: Path = Path(sys.executable).resolve()
    if executable.parent.name == "launcher":
        return executable.parent.parent
    return executable.parent


def _read_current(root: Path) -> dict[str, str]:
    try:
        with (root / "current.json").open(encoding="utf-8-sig") as fp:
            data = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "version": str(data.get("version") or ""),
        "previous": str(data.get("previous") or ""),
    }


def _read_build_info(version_dir: Path) -> dict[str, Any] | None:
    """宽松读取版本目录的 BUILD_INFO.json。

    Args:
        version_dir: ``versions/<v>`` 目录。

    Returns:
        字典；缺失或损坏时返回 ``None``，让 launcher 可回退旧版本。
    """
    try:
        with (version_dir / "BUILD_INFO.json").open(encoding="utf-8-sig") as fp:
            data: Any = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _confined_entry(version_dir: Path, entry_name: str) -> Path | None:
    """把 BUILD_INFO 的入口限制在版本目录内。

    Args:
        version_dir: ``versions/<v>`` 目录。
        entry_name: BUILD_INFO 中的入口相对路径。

    Returns:
        安全路径；非法时返回 ``None``。
    """
    name: str = str(entry_name or "").strip()
    if not name or "\x00" in name or ":" in name:
        return None
    normalized: str = name.replace("\\", "/")
    parts: tuple[str, ...] = PurePosixPath(normalized).parts
    if (
        not parts
        or PurePosixPath(normalized).is_absolute()
        or any(part in ("", ".", "..") for part in normalized.split("/"))
    ):
        return None
    root: Path = version_dir.resolve()
    try:
        candidate: Path = (root / Path(*parts)).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate


def _entry_path(root: Path, version: str) -> Path | None:
    """解析版本入口：优先 BUILD_INFO.entry，缺失时使用默认 exe。

    Args:
        root: 安装根目录。
        version: 版本目录名。

    Returns:
        可执行文件路径；无法解析时返回 ``None``。
    """
    version_dir: Path = root / "versions" / version
    info: dict[str, Any] | None = _read_build_info(version_dir)
    entry_name: str = str((info or {}).get("entry") or "").strip()
    if entry_name:
        candidate: Path | None = _confined_entry(version_dir, entry_name)
        return candidate if candidate is not None and candidate.is_file() else None
    fallback: Path = version_dir / ENTRY_NAME
    return fallback if fallback.is_file() else None


def _arguments() -> tuple[str, str, str]:
    version = ""
    data_root = ""
    notice = ""
    argv: list[str] = list(sys.argv[1:])
    index: int = 0
    while index < len(argv):
        item: str = argv[index]
        if item == "--version" and index + 1 < len(argv):
            version = argv[index + 1]
            index += 2
            continue
        if item == "--data-root" and index + 1 < len(argv):
            data_root = argv[index + 1]
            index += 2
            continue
        if item == "--update-ok":
            notice = "ok"
        elif item == "--update-failed":
            notice = "failed"
        index += 1
    return version, data_root, notice


def _show_error(root: Path) -> None:
    import ctypes

    ctypes.windll.user32.MessageBoxW(
        0,
        "程序启动失败。请到“关于 → 项目发布页”手动下载最新版本。\n\n安装目录：%s"
        % root,
        "HomeworkKiller4BJTU",
        0x10,
    )


def _launch(root: Path, version: str, data_root: Path, notice: str) -> bool:
    executable: Path | None = _entry_path(root, version)
    if executable is None:
        return False
    command: list[str] = [
        str(executable),
        "--data-root",
        str(data_root),
    ]
    if notice == "ok":
        command.append("--update-ok")
    elif notice == "failed":
        command.append("--update-failed")
    environment: dict[str, str] = dict(os.environ)
    environment["HWKLR_INSTALL_ROOT"] = str(root)
    environment["HWKLR_DATA_ROOT"] = str(data_root)
    flags: int = 0
    flags |= int(getattr(subprocess, "DETACHED_PROCESS", 0))
    flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        subprocess.Popen(
            command,
            cwd=str(root),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
    except OSError:
        return False
    return True


def main() -> int:
    root: Path = _install_root()
    state: dict[str, str] = _read_current(root)
    requested, data_root_arg, notice = _arguments()
    version = requested or state.get("version", "")
    previous = state.get("previous", "")
    data_root = Path(data_root_arg).resolve() if data_root_arg else root
    for candidate in (version, previous):
        if candidate and _launch(root, candidate, data_root, notice):
            return 0
    _show_error(root)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
