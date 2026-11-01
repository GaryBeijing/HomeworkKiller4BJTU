# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-01 12:40
# 文件名: manifest.py
# 主要用途: 登记官方功能模块与标签资源目录，供 UI 注册、构建导出与开发标记共同使用。
# 文件版本: 2.1.0
"""官方功能清单。

``OFFICIAL_FEATURES`` 是新增功能时必须同步维护的唯一清单：
- UI 层据此动态创建标签页（模块缺失时自动跳过，用于裁剪后的导出包）；
- 构建功能据此生成“Feature / 版本 / 开发构建”表格并决定打包范围。
"""
from __future__ import annotations

import importlib
from typing import Any, Final, NamedTuple

__version__ = "2.1.0"
__author__ = "Gary"
__all__ = [
    "FEATURE_BY_NAME",
    "FeatureSpec",
    "OFFICIAL_FEATURES",
    "feature_version",
    "load_feature_class",
]


class FeatureSpec(NamedTuple):
    """一个官方功能的静态描述。"""

    name: str
    """标签名称，同时作为 :class:`ViewParam` 的键。"""

    module: str
    """功能实现模块的完整导入路径。"""

    class_name: str
    """模块中功能类的名称。"""

    view_dir: str
    """``view_data`` 下的资源目录名。"""

    description: str
    """标签栏提示与关于页使用的功能说明。"""


OFFICIAL_FEATURES: Final[tuple[FeatureSpec, ...]] = (
    FeatureSpec(
        name="高铁纵横",
        module="hwklr.features.hsr",
        class_name="HSRFeature",
        view_dir="hsr",
        description="登录高铁答题系统，按题库自动匹配答案并提交考试。",
    ),
    FeatureSpec(
        name="C程序设计",
        module="hwklr.features.cprog",
        class_name="CProgrammingFeature",
        view_dir="cprog",
        description="CITEL 课程题目辅助：启发模式逐步讲解，题解模式生成并提交参考实现。",
    ),
    FeatureSpec(
        name="构建",
        module="hwklr.features.build",
        class_name="BuildFeature",
        view_dir="build",
        description="将当前程序导出为可直接运行的目录、zip 或可执行文件。",
    ),
)

FEATURE_BY_NAME: Final[dict[str, FeatureSpec]] = {
    spec.name: spec for spec in OFFICIAL_FEATURES
}


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
