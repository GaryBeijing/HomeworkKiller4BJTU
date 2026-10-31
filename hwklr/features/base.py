# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-01 00:01
# 文件名: base.py
# 主要用途: 定义所有功能都必须继承的 Feature 抽象基类、统一调用协议与设置组只读属性。
# 文件版本: 2.0.0
"""功能抽象基类。

约定：
- 每个功能继承 :class:`Feature`，在构造时接收 ``universal_param``；
- UI 通过 :meth:`Feature.handle` 以 ``action`` + ``params`` 的方式调用功能，
  功能与 UI 之间不直接依赖；
- 返回值统一为可 JSON 序列化的 ``dict``，至少包含 ``ok`` 字段。
"""
from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 避免 base 与 settings 相互导入。
    from .settings import FeatureSettingsGroup

__version__ = "2.0.0"
__all__ = ["Feature", "success", "failure"]

# 统一返回结构：ok 表示成功与否，data 放业务数据，error 放可读错误信息。
ApiResult = dict[str, Any]


def success(data: Any = None) -> ApiResult:
    """构造成功结果。

    Args:
        data: 业务数据，必须可被 JSON 序列化。

    Returns:
        形如 ``{"ok": True, "data": data}`` 的字典。
    """
    return {"ok": True, "data": data}


def failure(message: str, data: Any = None) -> ApiResult:
    """构造失败结果。

    Args:
        message: 面向用户的可读错误信息。
        data: 附加的调试/上下文数据，必须可被 JSON 序列化。

    Returns:
        形如 ``{"ok": False, "error": message, "data": data}`` 的字典。
    """
    return {"ok": False, "error": message, "data": data}


class Feature(abc.ABC):
    """功能抽象基类。

    子类必须实现 :meth:`handle`，按 ``action`` 分发具体业务逻辑。
    实例由 :class:`hwklr.UI.tagview.TagView` 创建并持有，生命周期与标签页一致。
    """

    def __init__(self, universal_param: dict[str, Any]) -> None:
        """初始化功能。

        Args:
            universal_param: 由窗口层注入的通用参数（运行期上下文、应用信息等）。
        """
        self._universal_param: dict[str, Any] = dict(universal_param or {})
        self._started: bool = False

    @property
    def universal_param(self) -> dict[str, Any]:
        """返回当前功能持有的通用参数副本。

        Returns:
            通用参数字典。
        """
        return dict(self._universal_param)

    @property
    def started(self) -> bool:
        """返回功能是否已启动。

        Returns:
            已启动为 ``True``，否则为 ``False``。
        """
        return self._started

    @property
    @abc.abstractmethod
    def settings_group(self) -> "FeatureSettingsGroup":
        """返回该功能注册到设置页的只读设置组。

        Returns:
            功能对应的 :class:`FeatureSettingsGroup`。
        """
        raise NotImplementedError

    def start(self) -> None:
        """启动功能。默认仅记录状态，子类可按需覆盖。"""
        self._started = True

    def stop(self) -> None:
        """停止功能。默认仅记录状态，子类可按需覆盖。"""
        self._started = False

    @abc.abstractmethod
    def handle(self, action: str, params: dict[str, Any]) -> ApiResult:
        """处理一次来自 UI 的动作调用。

        Args:
            action: 动作名称，例如 ``"login"``。
            params: 动作参数，必须来自 JSON 对象。

        Returns:
            统一格式的结果字典。

        Raises:
            ValueError: 动作不存在或参数不合法时由子类抛出。
        """
        raise NotImplementedError
