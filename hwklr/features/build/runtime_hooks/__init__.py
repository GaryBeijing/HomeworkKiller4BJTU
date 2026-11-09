# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-09 19:05
# 文件名: __init__.py
# 主要用途: 构建功能的 PyInstaller 运行时钩子集合。
# 文件版本: 1.0.0
"""PyInstaller 运行时钩子包。

钩子文件由 :mod:`hwklr.features.build.packager` 通过 ``--runtime-hook``
传给 PyInstaller；应用运行时不会导入本包。
"""
from __future__ import annotations

__version__ = "1.0.0"
__author__ = "Gary"
__all__: list[str] = []
