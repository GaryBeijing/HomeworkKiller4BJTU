# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-11 21:00
# 文件名: __init__.py
# 主要用途: 跨平台更新器门面：对外只暴露 UpdateService、平台选择与启动清理。
# 文件版本: 4.5.0
"""跨平台自动更新器。"""
from __future__ import annotations

from .core import (
    AUTO_ASSET_RE,
    MD5_ASSET_RE,
    UpdateService,
    bootstrap_current_version,
    cleanup_incomplete_update,
    select_auto_asset,
    select_md5_asset,
    updates_dir,
)
from .installers import get_platform_installer

__version__ = "4.5.0"
__author__ = "Gary"
__all__ = [
    "AUTO_ASSET_RE",
    "MD5_ASSET_RE",
    "UpdateService",
    "bootstrap_current_version",
    "cleanup_incomplete_update",
    "get_platform_installer",
    "select_auto_asset",
    "select_md5_asset",
    "updates_dir",
]
