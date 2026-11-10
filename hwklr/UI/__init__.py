# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-10 23:20
# 文件名: __init__.py
# 主要用途: UI 包门面：导出 WindowView 与 BridgeApi；具体实现拆分到 bridge/registry/extension_runtime/window。
# 文件版本: 4.4.1
"""UI 窗口层门面。

入口只需::

    window = WindowView()
    window.run()
"""
from __future__ import annotations

from .bridge import BridgeApi
from .window import WindowView

__version__ = "4.4.1"
__author__ = "Gary"
__all__ = ["BridgeApi", "WindowView"]
