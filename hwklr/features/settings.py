# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 文件名: settings.py
# 主要用途: 实现“设置”标签页的后端动作：账号密码、知识库信息、端口展示。
# 文件版本: 1.0.0
"""设置功能。

设置页只通过本功能读写配置，不直接操作文件，保证与核心逻辑解耦。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Final

from hwklr import __version__ as APP_VERSION
from hwklr import runtime_data
from hwklr.config import load_config, update_config
from hwklr.features.base import ApiResult, Feature, failure, success

__version__ = "1.0.0"
__all__ = ["SettingsFeature"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class SettingsFeature(Feature):
    """“设置”标签页功能。"""

    def handle(self, action: str, params: dict[str, Any]) -> ApiResult:
        """分发设置页动作。

        Args:
            action: 动作名称。
            params: 动作参数。

        Returns:
            统一格式的结果字典。
        """
        handlers: dict[str, Callable[[dict[str, Any]], ApiResult]] = {
            "get_settings": self._action_get_settings,
            "save_settings": self._action_save_settings,
            "get_bank_info": self._action_get_bank_info,
        }
        handler: Callable[[dict[str, Any]], ApiResult] | None = handlers.get(action)
        if handler is None:
            return failure("未知动作: %s" % action)
        try:
            return handler(params)
        except (OSError, ValueError) as exc:
            return failure(str(exc))
        except Exception as exc:  # 兜底，保证错误能回传到 UI。
            _LOGGER.exception("设置功能异常")
            return failure("操作失败: %s" % exc)

    def _action_get_settings(self, params: dict[str, Any]) -> ApiResult:
        """读取当前设置。

        Args:
            params: 未使用的动作参数。

        Returns:
            账号、密码、监听端口与版本信息。
        """
        config: dict[str, Any] = load_config()
        context: dict[str, Any] = self._universal_param.get("context", {})
        return success({
            "username": str(config.get("username") or ""),
            "password": str(config.get("password") or ""),
            "port": int(context.get("port", 0)),
            "version": APP_VERSION,
        })

    def _action_save_settings(self, params: dict[str, Any]) -> ApiResult:
        """保存账号与密码设置。

        Args:
            params: 可包含 ``username``、``password``。

        Returns:
            保存后的设置。
        """
        username: str = str(params.get("username") or "").strip()
        password: str = str(params.get("password") or "").strip()
        update_config({"username": username, "password": password})
        return success({"username": username, "saved": True})

    def _action_get_bank_info(self, params: dict[str, Any]) -> ApiResult:
        """列出所有功能的知识库及题量。

        Args:
            params: 未使用的动作参数。

        Returns:
            形如 ``{"banks": [...]}`` 的结果。
        """
        banks: list[dict[str, Any]] = []
        for feature_name, versions in runtime_data.list_banks().items():
            for version in versions:
                try:
                    data: Any = runtime_data.load_bank(feature_name, version)
                    count: int = self._count_items(data)
                except (OSError, ValueError) as exc:
                    _LOGGER.warning("读取知识库失败 %s v%s: %s", feature_name, version, exc)
                    count = 0
                banks.append({
                    "feature": feature_name,
                    "version": version,
                    "count": count,
                })
        return success({"banks": banks})

    @staticmethod
    def _count_items(data: Any) -> int:
        """统计知识库条目数量。

        Args:
            data: ``json.load`` 后的知识库对象。

        Returns:
            条目数量。
        """
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            items: Any = data.get("items") or data.get("questions") or []
            return len(items) if isinstance(items, list) else 0
        return 0
