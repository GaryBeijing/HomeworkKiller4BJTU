# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-11 21:00
# 文件名: __init__.py
# 主要用途: 按当前平台惰性选择版本化安装器，避免把另一平台的代码打入包内。
# 文件版本: 4.5.0
"""平台安装器选择。"""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import PlatformInstaller

__version__ = "4.5.0"
__author__ = "Gary"
__all__ = ["get_platform_installer"]


def get_platform_installer() -> "PlatformInstaller":
    """返回当前平台的安装器。

    Raises:
        RuntimeError: 当前平台不受支持。
    """
    if sys.platform == "win32":
        from .windows import WindowsInstaller

        return WindowsInstaller()
    if sys.platform == "darwin":
        from .macos import MacOSInstaller

        return MacOSInstaller()
    raise RuntimeError("自动更新暂不支持当前平台：%s" % sys.platform)
