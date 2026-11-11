# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-11 21:00
# 文件名: base.py
# 主要用途: 平台安装器接口、ZIP 安全解压、BUILD_INFO 校验与 current.json 版本指针。
# 文件版本: 4.5.0
"""平台安装器公共逻辑。"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from hwklr.config import data_root, install_root

__version__ = "4.5.0"
__author__ = "Gary"
__all__ = [
    "InstallerError",
    "PlatformInstaller",
    "read_current",
    "safe_extract_zip",
    "write_current",
]

_LOGGER: logging.Logger = logging.getLogger(__name__)


class InstallerError(Exception):
    """安装/激活更新失败。"""


def read_current(root: Path | None = None) -> dict[str, str]:
    """读取 current.json。"""
    target: Path = (root or install_root()) / "current.json"
    try:
        with target.open(encoding="utf-8-sig") as fp:
            data: Any = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "version": str(data.get("version") or ""),
        "previous": str(data.get("previous") or ""),
    }


def write_current(version: str, previous: str = "", root: Path | None = None) -> None:
    """原子写入 current.json。"""
    base: Path = root or install_root()
    base.mkdir(parents=True, exist_ok=True)
    target: Path = base / "current.json"
    temporary: Path = target.with_suffix(".json.tmp")
    payload: dict[str, str] = {"version": str(version)}
    if previous:
        payload["previous"] = str(previous)
    with temporary.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
        fp.write("\n")
    temporary.replace(target)


def safe_extract_zip(archive: Path, target: Path) -> None:
    """安全解压 ZIP，拒绝绝对路径与 ``..`` 逃逸。"""
    destination: Path = target.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            name: str = member.filename.replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            relative: Path = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise InstallerError("更新包包含非法路径：%s" % member.filename)
            final: Path = (destination / relative).resolve()
            try:
                final.relative_to(destination)
            except ValueError as exc:
                raise InstallerError("更新包路径越界：%s" % member.filename) from exc
            final.parent.mkdir(parents=True, exist_ok=True)
            with package.open(member) as source, final.open("wb") as output:
                shutil.copyfileobj(source, output)


class PlatformInstaller(ABC):
    """平台安装器基类。子类只实现与平台相关的部分。"""

    platform: str = ""
    entry_name: str = ""

    @property
    def arch(self) -> str:
        """返回标准化架构名。"""
        import platform as platform_module

        machine: str = platform_module.machine().lower()
        if machine in ("amd64", "x86_64", "x64"):
            return "x64"
        if machine in ("arm64", "aarch64"):
            return "arm64"
        return machine or "x64"

    def platform_tags(self) -> tuple[str, ...]:
        """返回资产选择使用的平台/架构标记。"""
        return (self.platform, self.arch)

    def install_root(self) -> Path:
        """返回安装根目录。"""
        return install_root()

    def data_root(self) -> Path:
        """返回用户数据根目录。"""
        return data_root()

    def is_supported(self) -> bool:
        """当前是否支持版本化安装。源码运行不支持。"""
        return bool(getattr(sys, "frozen", False))

    def version_dir(self, version: str) -> Path:
        """返回版本目录。"""
        return self.install_root() / "versions" / str(version)

    def current_version(self) -> str:
        """返回 current.json 中的当前版本。"""
        return read_current(self.install_root()).get("version", "")

    def extract(self, archive: Path, target: Path) -> None:
        """默认 ZIP 解压；macOS 可覆盖为 ditto。"""
        safe_extract_zip(archive, target)

    def build_info(self, staged: Path) -> dict[str, Any]:
        """读取 staging 中的 BUILD_INFO.json。"""
        candidate: Path = staged / "BUILD_INFO.json"
        if not candidate.is_file():
            raise InstallerError("更新包缺少 BUILD_INFO.json")
        try:
            with candidate.open(encoding="utf-8-sig") as fp:
                data: Any = json.load(fp)
        except (OSError, json.JSONDecodeError) as exc:
            raise InstallerError("BUILD_INFO.json 无法解析：%s" % exc) from exc
        if not isinstance(data, dict):
            raise InstallerError("BUILD_INFO.json 内容不合法")
        return data

    def validate(self, staged: Path, version: str) -> Path:
        """校验版本/平台/架构并返回入口文件。"""
        info: dict[str, Any] = self.build_info(staged)
        expected_version: str = str(version).lstrip("vV")
        actual_version: str = str(info.get("version") or "").lstrip("vV")
        # 发布 tag 通常是三段版本，BUILD_INFO 可能是四段导出号；比较前三段。
        expected_parts: list[str] = expected_version.split(".")[:3]
        actual_parts: list[str] = actual_version.split(".")[:3]
        if actual_parts != expected_parts:
            raise InstallerError(
                "更新包版本不匹配：期望 %s，实际 %s"
                % (expected_version, actual_version)
            )
        if str(info.get("platform") or "").lower() != self.platform:
            raise InstallerError(
                "更新包平台不匹配：期望 %s，实际 %s"
                % (self.platform, info.get("platform"))
            )
        if str(info.get("arch") or "").lower() != self.arch:
            raise InstallerError(
                "更新包架构不匹配：期望 %s，实际 %s"
                % (self.arch, info.get("arch"))
            )
        entry_name: str = str(info.get("entry") or self.entry_name or "")
        entry: Path = staged / entry_name
        if not entry.exists():
            raise InstallerError("更新包缺少入口：%s" % entry_name)
        return entry

    def activate(self, staged: Path, version: str) -> Path:
        """把 staging 移动到 versions/<version>。

        不覆盖正在运行的旧版本；目标版本已存在时拒绝。
        """
        target: Path = self.version_dir(version)
        if target.exists():
            raise InstallerError("目标版本目录已存在：%s" % target)
        target.parent.mkdir(parents=True, exist_ok=True)
        # 先移动到 versions 同卷的临时目录，再用 rename 原子切换；
        # 跨卷（如 macOS 数据目录 -> 安装目录）中途失败不会污染目标版本。
        working: Path = target.parent / (".staging-" + target.name)
        if working.exists():
            shutil.rmtree(working, ignore_errors=True)
        try:
            shutil.move(str(staged), str(working))
            if target.exists():
                raise InstallerError("目标版本目录已存在：%s" % target)
            os.replace(working, target)
        except OSError as exc:
            shutil.rmtree(working, ignore_errors=True)
            raise InstallerError("移动更新目录失败：%s" % exc) from exc
        return target

    def write_current(self, version: str, previous: str = "") -> None:
        """写入 current.json。"""
        write_current(version, previous, self.install_root())

    def cleanup_old_versions(self) -> None:
        """只保留 current 与 previous 两个版本目录。"""
        state: dict[str, str] = read_current(self.install_root())
        keep: set[str] = {
            state.get("version", ""),
            state.get("previous", ""),
        }
        versions_dir: Path = self.install_root() / "versions"
        if not versions_dir.is_dir():
            return
        for child in versions_dir.iterdir():
            if not child.is_dir() or child.name in keep:
                continue
            # 不删除当前正在运行的版本目录。
            try:
                Path(sys.executable).resolve().relative_to(child.resolve())
                continue
            except ValueError:
                pass
            try:
                shutil.rmtree(child)
            except OSError:
                _LOGGER.warning("清理旧版本失败：%s", child, exc_info=True)

    @abstractmethod
    def restart(self, version: str, notice: str = "") -> bool:
        """启动新版本；返回是否成功创建进程。"""

    def rollback(self) -> str | None:
        """把 current.json 指回 previous 并返回该版本。"""
        state: dict[str, str] = read_current(self.install_root())
        previous: str = state.get("previous", "")
        if not previous:
            return None
        current: str = state.get("version", "")
        write_current(previous, current, self.install_root())
        return previous
