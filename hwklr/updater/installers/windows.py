# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-11 21:00
# 文件名: windows.py
# 主要用途: Windows 版本化安装器：ZIP 解压、versions 目录切换、launcher 重启与回滚。
# 文件版本: 4.5.0
"""Windows 平台安装器。"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .base import InstallerError, PlatformInstaller

__version__ = "4.5.0"
__author__ = "Gary"
__all__ = ["WindowsInstaller"]

_LOGGER: logging.Logger = logging.getLogger(__name__)


class WindowsInstaller(PlatformInstaller):
    """Windows onedir 版本化安装器。"""

    platform = "windows"
    entry_name = "HomeworkKiller4BJTU.exe"

    def is_supported(self) -> bool:
        """源码运行或没有安装根目录写权限时不支持。"""
        if not super().is_supported():
            return False
        try:
            self.install_root().mkdir(parents=True, exist_ok=True)
            probe: Path = self.install_root() / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError:
            return False
        return True

    def restart(self, version: str, notice: str = "") -> bool:
        """优先通过 launcher 启动新版本；没有 launcher 时直接启动版本 exe。"""
        version_dir: Path = self.version_dir(version)
        executable: Path = version_dir / self.entry_name
        if not executable.is_file():
            raise InstallerError("新版本缺少可执行文件：%s" % executable)
        launcher: Path = self.install_root() / "launcher" / self.entry_name
        command: list[str]
        if launcher.is_file():
            command = [
                str(launcher),
                "--version",
                version,
                "--data-root",
                str(self.data_root()),
            ]
        else:
            command = [
                str(executable),
                "--data-root",
                str(self.data_root()),
            ]
        if notice == "ok":
            command.append("--update-ok")
        elif notice == "failed":
            command.append("--update-failed")
        flags: int = 0
        flags |= int(getattr(subprocess, "DETACHED_PROCESS", 0))
        flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        try:
            subprocess.Popen(
                command,
                cwd=str(self.install_root()),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                close_fds=True,
            )
        except OSError:
            _LOGGER.exception("启动新版本失败")
            return False
        return True

    def rollback(self) -> str | None:
        """回滚 current.json 并启动上一版本。"""
        previous: str | None = super().rollback()
        if previous:
            self.restart(previous, notice="failed")
        return previous
