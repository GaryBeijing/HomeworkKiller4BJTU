# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-01 12:40
# 文件名: __init__.py
# 主要用途: 汇总导出 Feature 抽象、核心功能与官方功能清单；可选功能按需加载，支持导出裁剪。
# 文件版本: 2.1.0
"""功能包。

对外统一暴露 :class:`Feature` 抽象及各标签页对应功能类。可选功能类采用
惰性导入：某个功能模块在裁剪后的导出包中不存在时，不影响其余功能启动。
"""
from __future__ import annotations

from typing import Any

from .about import AboutFeature
from .base import ApiResult, Feature, failure, success
from .manifest import FEATURE_BY_NAME, OFFICIAL_FEATURES, FeatureSpec, load_feature_class
from .settings import FeatureSettingsGroup, SettingsFeature, SettingsFieldSpec

__version__ = "2.1.0"
__author__ = "Gary"
__all__ = [
    "AboutFeature",
    "ApiResult",
    "BuildFeature",
    "CProgrammingFeature",
    "FEATURE_BY_NAME",
    "Feature",
    "FeatureSettingsGroup",
    "FeatureSpec",
    "HSRFeature",
    "OFFICIAL_FEATURES",
    "SettingsFeature",
    "SettingsFieldSpec",
    "failure",
    "success",
]

# 可选功能的类名到清单项的映射；首次访问时才导入对应模块。
_FEATURE_IMPORTS: dict[str, FeatureSpec] = {
    spec.class_name: spec for spec in OFFICIAL_FEATURES
}


def __getattr__(name: str) -> Any:
    """按需加载可选功能类（PEP 562）。

    Args:
        name: 属性名，例如 ``"HSRFeature"``。

    Returns:
        对应的功能类。

    Raises:
        AttributeError: 名称未登记或模块已被裁剪时抛出。
    """
    spec: FeatureSpec | None = _FEATURE_IMPORTS.get(name)
    if spec is None:
        raise AttributeError("module %r has no attribute %r" % (__name__, name))
    feature_cls: Any = load_feature_class(spec.module, spec.class_name)
    if feature_cls is None:
        raise AttributeError("功能模块不可用: %s" % spec.module)
    globals()[name] = feature_cls
    return feature_cls
