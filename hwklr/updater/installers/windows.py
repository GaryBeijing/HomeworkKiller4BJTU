# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-11 21:00
# 最后更新: 2026-11-12 16:50
# 文件名: windows.py
# 主要用途: Windows 版本化安装器：ZIP 解压、versions 目录切换、按 BUILD_INFO 入口启动 launcher 与回滚。
# 文件版本: 4.6.3
"""Windows 平台安装器。"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .base import InstallerError, PlatformInstaller

__version__ = "4.6.3"
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

    def _launcher_path(self, entry_filename: str) -> Path | None:
        """按版本入口名与默认名依次查找 launcher。

        Args:
            entry_filename: 新版本 BUILD_INFO 指定的入口文件名。

        Returns:
            存在的 launcher 路径；都没有时返回 ``None``。
        """
        launcher_dir: Path = self.install_root() / "launcher"
        for name in (entry_filename, self.entry_name):
            candidate: Path = launcher_dir / name
            if candidate.is_file():
                return candidate
        return None

    def restart(self, version: str, notice: str = "") -> bool:
        """优先通过 launcher 启动新版本；没有 launcher 时直接启动版本 exe。"""
        version_dir: Path = self.version_dir(version)
        executable: Path = self.resolve_entry(version_dir)
        launcher: Path | None = self._launcher_path(executable.name)
        command: list[str]
        if launcher is not None:
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

    def rollback(self, *, launch: bool = True) -> str | None:
        """回滚 current.json，并在 ``launch`` 为真时启动上一版本。"""
        previous: str | None = super().rollback()
        if previous and launch:
            try:
                self.restart(previous, notice="failed")
            except (InstallerError, OSError):
                _LOGGER.warning("回滚后启动上一版本失败", exc_info=True)
        return previous
