# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-11 21:00
# 文件名: launcher_macos.py
# 主要用途: macOS 稳定启动器：读取 current.json 并启动 versions/<v> 中的 .app，失败时回退上一版本。
# 文件版本: 4.5.0
"""macOS launcher（仅启动逻辑，不含业务代码）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

__version__ = "4.5.0"
__author__ = "Gary"
__all__ = ["main"]

ENTRY_NAME = "HomeworkKiller4BJTU.app"


def _install_root() -> Path:
    env_value: str = str(os.environ.get("HWKLR_INSTALL_ROOT") or "").strip()
    if env_value:
        return Path(env_value).resolve()
    executable: Path = Path(sys.executable).resolve()
    for parent in executable.parents:
        if parent.name in ("launcher", "versions"):
            return parent.parent
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
    message = "程序启动失败。请到“关于 → 项目发布页”手动下载最新版本。"
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                'display alert "HomeworkKiller4BJTU" message "%s" as critical'
                % message,
            ],
            check=False,
        )
    except OSError:
        pass


def _launch(root: Path, version: str, data_root: Path, notice: str) -> bool:
    app: Path = root / "versions" / version / ENTRY_NAME
    if not app.is_dir():
        return False
    executable_dir: Path = app / "Contents" / "MacOS"
    binaries: list[Path] = (
        [item for item in executable_dir.iterdir() if item.is_file()]
        if executable_dir.is_dir()
        else []
    )
    environment: dict[str, str] = dict(os.environ)
    environment["HWKLR_INSTALL_ROOT"] = str(root)
    environment["HWKLR_DATA_ROOT"] = str(data_root)
    if binaries:
        command: list[str] = [str(binaries[0])]
        if notice == "ok":
            command.append("--update-ok")
        elif notice == "failed":
            command.append("--update-failed")
        try:
            subprocess.Popen(
                command,
                cwd=str(root),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
            return True
        except OSError:
            return False
    try:
        subprocess.Popen(["open", "-n", str(app)], close_fds=True)
    except OSError:
        return False
    return True


def main() -> int:
    root: Path = _install_root()
    state: dict[str, str] = _read_current(root)
    requested, data_root_arg, notice = _arguments()
    version = requested or state.get("version", "")
    previous = state.get("previous", "")
    data_root = Path(data_root_arg).resolve() if data_root_arg else Path.home() / "Library" / "Application Support" / "HomeworkKiller4BJTU"
    for candidate in (version, previous):
        if candidate and _launch(root, candidate, data_root, notice):
            return 0
    _show_error(root)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
