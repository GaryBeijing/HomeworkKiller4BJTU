# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 文件名: about.py
# 主要用途: 实现“关于”标签页的后端动作，提供软件名称、版本、作者与声明。
# 文件版本: 1.0.0
"""关于功能。"""
from __future__ import annotations

from typing import Any

from hwklr.features.base import ApiResult, Feature, failure, success

__version__ = "1.0.0"
__all__ = ["AboutFeature"]


class AboutFeature(Feature):
    """“关于”标签页功能。"""

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
