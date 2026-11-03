# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-03 20:15
# 文件名: __init__.py
# 主要用途: 插件工程模板入口：提供一个可正常加载的最小 Feature，供开发者继续扩展。
# 文件版本: 1.0.0
"""插件工程模板。

``__all__`` 中有且仅有一个 Feature 类名；新建插件工程时会替换
``__FEATURE_NAME__`` 与 ``__PACKAGE_NAME__`` 占位符。
"""
from __future__ import annotations

from typing import Any

from hwklr.features.about import AboutMetadataGroup
from hwklr.features.base import ApiResult, Feature, failure, success
from hwklr.features.settings import FeatureSettingsGroup

__version__ = "1.0.0.0"
__author__ = "Gary"
__feature_name__ = "__FEATURE_NAME__"
__package_name__ = "__PACKAGE_NAME__"
__update_date__ = "2026-11-03"
__official__ = False
__all__ = ["HelloPluginFeature"]


class HelloPluginFeature(Feature):
    """模板插件功能：返回一句欢迎语。"""

    def __init__(self, universal_param: dict[str, Any]) -> None:
        """初始化模板插件。

        Args:
            universal_param: 窗口层注入的通用参数。
        """
        super().__init__(universal_param)
        self._settings_group: FeatureSettingsGroup = FeatureSettingsGroup(
            group_id="__PACKAGE_NAME__",
            title=__feature_name__,
            description="模板插件暂时没有可配置项。",
            field_specs=(),
            values_getter=lambda: {},
            exporter=lambda values: {},
            complete_checker=lambda: True,
            missing_getter=lambda: [],
        )

    @property
    def settings_group(self) -> FeatureSettingsGroup:
        """返回模板插件的设置组。

        Returns:
            空设置组；窗口层会自动为其绑定启用开关。
        """
        return self._settings_group

    @property
    def about_meta(self) -> AboutMetadataGroup:
        """返回模板插件在“关于”页的元信息。

        Returns:
            插件元信息组。
        """
        return AboutMetadataGroup(
            name=__feature_name__,
            package=__package_name__,
            author=__author__,
            version=__version__,
            update_date=__update_date__,
            official=False,
            feature_key=__feature_name__,
            description="由插件工程模板创建的示例插件。",
        )

    def handle(self, action: str, params: dict[str, Any]) -> ApiResult:
        """分发模板插件动作。

        Args:
            action: 动作名称。
            params: 动作参数。

        Returns:
            统一格式的结果字典。
        """
        if action == "hello":
            return success({"message": "欢迎你，开发者！"})
        return failure("未知动作: %s" % action)
