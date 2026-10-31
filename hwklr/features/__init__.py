# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 文件名: __init__.py
# 主要用途: 汇总导出所有功能类与 Feature 抽象。
# 文件版本: 1.0.0
"""功能包。

对外统一暴露 :class:`Feature` 抽象及各标签页对应功能类，UI 层只需
``from hwklr.features import HSRFeature`` 即可使用。
"""
from __future__ import annotations

from .about import AboutFeature
from .base import ApiResult, Feature, failure, success
from .hsr import HSRFeature
from .settings import SettingsFeature

__version__ = "1.0.0"
__author__ = "Gary"
__all__ = [
    "AboutFeature",
    "ApiResult",
    "Feature",
    "HSRFeature",
    "SettingsFeature",
    "failure",
    "success",
]
