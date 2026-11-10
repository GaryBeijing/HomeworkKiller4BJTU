# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-10 23:59
# 文件名: base.py
# 主要用途: 定义所有功能都必须继承的 Feature 抽象基类、统一调用协议、Action 校验、设置组、数据库访问与关于元信息只读属性。
# 文件版本: 4.4.2
"""功能抽象基类。

约定：
- 每个功能继承 :class:`Feature`，在构造时接收 ``universal_param``；
- UI 通过 :meth:`Feature.handle` 以 ``action`` + ``params`` 的方式调用功能，
  功能与 UI 之间不直接依赖；
- 返回值统一为可 JSON 序列化的 ``dict``，至少包含 ``ok`` 字段。
"""
from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any, final

from hwklr import db
from hwklr.contracts import (
    ActionRegistry,
    ActionSpec,
    ActionValidationError,
    ApiResult,
    ErrorCode,
)

if TYPE_CHECKING:  # 避免 base 与 settings/about 相互导入。
    from .about import AboutMetadataGroup
    from .settings import FeatureSettingsGroup

__version__ = "4.4.2"
__all__ = ["ApiResult", "Feature", "success", "failure"]


def success(
    data: Any = None, *, code: str = ErrorCode.OK.value
) -> ApiResult:
    """构造成功结果。

    Args:
        data: 业务数据，必须可被 JSON 序列化。
        code: 稳定的成功码；默认 ``ok``。

    Returns:
        形如 ``{"ok": True, "data": data, "code": code}`` 的字典。
    """
    return {"ok": True, "data": data, "code": code}


def failure(
    message: str,
    data: Any = None,
    *,
    code: str = ErrorCode.UNKNOWN.value,
) -> ApiResult:
    """构造失败结果。

    Args:
        message: 面向用户的可读错误信息。
        data: 附加的调试/上下文数据，必须可被 JSON 序列化。
        code: 稳定的错误码；默认 ``unknown``。

    Returns:
        形如 ``{"ok": False, "error": message, "data": data, "code": code}`` 的字典。
    """
    return {"ok": False, "error": message, "data": data, "code": code}


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
        # 功能使用的数据库名称；空字符串表示不启用数据库。
        self._db_base_name: str = ""

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

    @property
    @abc.abstractmethod
    def about_meta(self) -> "AboutMetadataGroup":
        """返回该功能注册到“关于”页的只读元信息组。

        Returns:
            功能对应的 :class:`AboutMetadataGroup`。
        """
        raise NotImplementedError

    def start(self) -> None:
        """启动功能。默认仅记录状态，子类可按需覆盖。"""
        self._started = True

    def stop(self) -> None:
        """停止功能。默认仅记录状态，子类可按需覆盖。

        注意：切换标签只调用本方法；后台 Job 不应在这里取消。
        """
        self._started = False

    def shutdown(self) -> None:
        """关闭功能持有的后台任务。

        仅在窗口关闭时调用；默认 no-op，拥有后台 Job 的功能应覆盖本方法，
        使用有界 join 取消/等待任务，避免阻塞应用退出。
        """
        self.stop()

    @final
    def _load_db(self, id: int) -> dict[str, Any] | None:
        """读取本功能对应的数据库记录。

        未配置 ``_db_base_name`` 时抛出 :class:`hwklr.db.DbDisabledError`。
        调用方应只在动作处理路径使用本方法，让 ``handle()`` / 桥接层把异常
        转换为可读错误，避免影响程序启动。

        Args:
            id: 数据库记录编号，由功能与对应 provider 约定。

        Returns:
            数据库中的 JSON 对象；provider 没有可用数据时返回 ``None``。

        Raises:
            db.DbDisabledError: 功能未配置 ``_db_base_name``。
            db.DbProviderNotFoundError: 没有与 ``_db_base_name`` 匹配的 provider。
            db.DbError: 数据库读取或落盘失败。
        """
        if not self._db_base_name:
            raise db.DbDisabledError(
                "功能 %s 未配置 _db_base_name，数据库不可用" % type(self).__name__
            )
        payload: Any = db.get_db_manager().load(self._db_base_name, int(id))
        if payload is not None and not isinstance(payload, dict):
            raise db.DbFormatError(
                "数据库 %s 的 id=%s 不是 JSON 对象" % (self._db_base_name, id)
            )
        return payload

    @classmethod
    def action_specs(cls) -> tuple[ActionSpec, ...]:
        """返回该功能声明的动作规格。

        默认空元组表示继续走旧 ``handle`` 行为；声明后由 :meth:`dispatch`
        做宽松参数校验。
        """
        return ()

    @final
    def dispatch(self, action: str, params: dict[str, Any]) -> ApiResult:
        """校验并分发一次 UI 动作。

        Args:
            action: 动作名称。
            params: 动作参数。

        Returns:
            统一格式的结果字典。
        """
        if not isinstance(params, dict):
            return failure("动作参数必须是对象", code=ErrorCode.INVALID_PARAMS.value)
        specs = type(self).action_specs()
        if not specs:
            return self.handle(action, params)
        registry = ActionRegistry(specs)
        spec = registry.get(action)
        if spec is None:
            # 保留各功能原有的“未知动作”错误文案。
            return self.handle(action, params)
        try:
            validated = registry.validate(spec, params)
        except ActionValidationError as exc:
            return failure(str(exc), code=ErrorCode.INVALID_PARAMS.value)
        return self.handle(spec.name, validated)

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
