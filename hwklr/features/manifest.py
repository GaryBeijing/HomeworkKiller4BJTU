# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-01 12:40
# 最后更新: 2026-11-10 10:30
# 文件名: manifest.py
# 主要用途: 登记官方功能模块与标签资源目录，供 UI 注册、构建导出与开发标记共同使用。
# 文件版本: 4.4.0
"""官方功能清单。

``OFFICIAL_FEATURES`` 是新增功能时必须同步维护的唯一清单：
- UI 层据此动态创建标签页（模块缺失时自动跳过，用于裁剪后的导出包）；
- 构建功能据此生成“Feature / 版本 / 开发构建”表格并决定打包范围。
"""
from __future__ import annotations

import importlib
from typing import Any, Final

from hwklr.feature_specs import (
    FEATURE_BY_ID,
    FEATURE_BY_NAME,
    OFFICIAL_FEATURES,
    FeatureSpec,
    build_features_default,
    feature_config_defaults,
    feature_order,
    feature_provider_specs,
    official_sections,
)

__version__ = "4.4.0"
__author__ = "Gary"
__all__ = [
    "FEATURE_BY_ID",
    "FEATURE_BY_NAME",
    "FeatureSpec",
    "OFFICIAL_FEATURES",
    "build_features_default",
    "feature_config_defaults",
    "feature_order",
    "feature_provider_specs",
    "feature_version",
    "load_feature_class",
    "official_sections",
]


def load_feature_class(module_name: str, class_name: str) -> type[Any] | None:
    """动态加载功能类。

    Args:
        module_name: 功能模块的完整导入路径。
        class_name: 功能类名称。

    Returns:
        找到的类；模块被裁剪或未定义该类时返回 ``None``。
    """
    try:
        module: Any = importlib.import_module(module_name)
    except ImportError:
        return None
    candidate: Any = getattr(module, class_name, None)
    return candidate if isinstance(candidate, type) else None


def feature_version(spec: FeatureSpec) -> str:
    """读取功能模块的版本号。

    Args:
        spec: 功能描述。

    Returns:
        模块的 ``__version__``；模块缺失时返回 ``"0.0.0"``。
    """
    try:
        module: Any = importlib.import_module(spec.module)
    except ImportError:
        return "0.0.0"
    return str(getattr(module, "__version__", "0.0.0"))
