# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-01 00:01
# 文件名: about.py
# 主要用途: 实现“关于”标签页功能，并提供空设置组以满足 TagView 的统一属性约束。
# 文件版本: 2.0.0
"""关于功能。"""
from __future__ import annotations

from typing import Any

from hwklr.features.base import ApiResult, Feature, failure, success
from hwklr.features.settings import FeatureSettingsGroup

__version__ = "2.0.0"
__author__ = "Gary"
__all__ = ["AboutFeature"]


class AboutFeature(Feature):
    """“关于”标签页功能。"""

    def __init__(self, universal_param: dict[str, Any]) -> None:
        """初始化关于功能。

        Args:
            universal_param: 窗口层注入的通用参数。
        """
        super().__init__(universal_param)
        self._settings_group: FeatureSettingsGroup = FeatureSettingsGroup(
            group_id="about",
            title="关于",
            description="",
            field_specs=(),
            values_getter=lambda: {},
            exporter=lambda values: {},
            complete_checker=lambda: True,
            missing_getter=lambda: [],
        )

    @property
    def settings_group(self) -> FeatureSettingsGroup:
        """返回空的设置组。

        Returns:
            无字段的设置组。
        """
        return self._settings_group

    def handle(self, action: str, params: dict[str, Any]) -> ApiResult:
        """分发关于页动作。

        Args:
            action: 动作名称。
            params: 动作参数。

        Returns:
            统一格式的结果字典。
        """
        if action == "get_meta":
            return self._action_get_meta(params)
        return failure("未知动作: %s" % action)

    def _action_get_meta(self, params: dict[str, Any]) -> ApiResult:
        """返回应用元信息。

        Args:
            params: 未使用的动作参数。

        Returns:
            应用名称、版本、作者、简介、声明与功能列表。
        """
        meta: Any = self._universal_param.get("app_meta") or {}
        if not isinstance(meta, dict):
            meta = {}
        return success(meta)
