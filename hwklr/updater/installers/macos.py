# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-11 21:00
# 文件名: macos.py
# 主要用途: macOS 版本化安装器：ditto 解压、.app 校验/签名检查、open 重启与回滚。
# 文件版本: 4.5.0
"""macOS 平台安装器。"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from .base import InstallerError, PlatformInstaller, safe_extract_zip

__version__ = "4.5.0"
__author__ = "Gary"
__all__ = ["MacOSInstaller"]

_LOGGER: logging.Logger = logging.getLogger(__name__)


class MacOSInstaller(PlatformInstaller):
    """macOS .app bundle 版本化安装器。"""

    platform = "macos"
    entry_name = "HomeworkKiller4BJTU.app"

    def extract(self, archive: Path, target: Path) -> None:
        """优先用 ditto 保留 .app 符号链接与资源分叉。"""
        target.mkdir(parents=True, exist_ok=True)
        try:
            completed = subprocess.run(
                ["ditto", "-x", "-k", str(archive), str(target)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError:
            completed = None
        if completed is None or completed.returncode != 0:
            try:
                safe_extract_zip(archive, target)
            except Exception as exc:
                raise InstallerError("macOS 更新包解压失败：%s" % exc) from exc

    def _app_path(self, staged: Path) -> Path:
        """定位 staging 中的 .app。"""
        direct: Path = staged / self.entry_name
        if direct.is_dir():
            return direct
        apps: list[Path] = sorted(staged.glob("*.app"))
        if len(apps) == 1:
            return apps[0]
        raise InstallerError("更新包中未找到唯一的 .app")

    def build_info(self, staged: Path) -> dict[str, Any]:
        """macOS 的 BUILD_INFO 可在 app 同级或 Contents/Resources 内。"""
        candidates: list[Path] = [staged / "BUILD_INFO.json"]
        try:
            app: Path | None = self._app_path(staged)
        except InstallerError:
            app = None
        if app is not None:
            candidates.append(app / "Contents" / "Resources" / "BUILD_INFO.json")
        for candidate in candidates:
            if candidate.is_file():
                import json

                try:
                    with candidate.open(encoding="utf-8-sig") as fp:
                        data: Any = json.load(fp)
                except (OSError, json.JSONDecodeError) as exc:
                    raise InstallerError("BUILD_INFO.json 无法解析：%s" % exc) from exc
                if isinstance(data, dict):
                    return data
                raise InstallerError("BUILD_INFO.json 内容不合法")
        raise InstallerError("更新包缺少 BUILD_INFO.json")

    def validate(self, staged: Path, version: str) -> Path:
        """校验版本/平台/架构、入口与代码签名。"""
        entry: Path = super().validate(staged, version)
        app: Path = self._app_path(staged)
        # 签名/公证由发布流程保证；缺少 codesign 时只记录警告。
        try:
            result = subprocess.run(
                ["codesign", "--verify", "--deep", "--strict", str(app)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError:
            _LOGGER.warning("未找到 codesign，跳过 macOS 签名校验")
        else:
            if result.returncode != 0:
                raise InstallerError(
                    "macOS 更新包签名校验失败：%s" % result.stderr.strip()
                )
        return entry

    def restart(self, version: str, notice: str = "") -> bool:
        """通过 open 或直接执行 .app 主程序启动新版本。"""
        version_dir: Path = self.version_dir(version)
        try:
            app: Path = self._app_path(version_dir)
        except InstallerError as exc:
            raise InstallerError(str(exc)) from exc
        executable: Path = app / "Contents" / "MacOS"
        binaries: list[Path] = [
            item for item in executable.iterdir() if item.is_file()
        ] if executable.is_dir() else []
        environment: dict[str, str] = dict(os.environ)
        environment["HWKLR_DATA_ROOT"] = str(self.data_root())
        environment["HWKLR_INSTALL_ROOT"] = str(self.install_root())
        if binaries:
            command = [str(binaries[0])]
            if notice == "ok":
                command.append("--update-ok")
            elif notice == "failed":
                command.append("--update-failed")
            try:
                subprocess.Popen(
                    command,
                    cwd=str(self.install_root()),
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    start_new_session=True,
                )
            except OSError:
                _LOGGER.exception("启动 macOS 新版本失败")
                return False
            return True
        try:
            subprocess.Popen(["open", "-n", str(app)], close_fds=True)
        except OSError:
            _LOGGER.exception("open .app 失败")
            return False
        return True

    def rollback(self) -> str | None:
        """回滚并启动上一版本。"""
        previous: str | None = super().rollback()
        if previous:
            self.restart(previous, notice="failed")
        return previous
