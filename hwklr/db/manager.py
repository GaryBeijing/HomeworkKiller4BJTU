# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 13:26
# 文件名: manager.py
# 主要用途: 实例化并注册所有 DbProvider，提供按数据库名称访问数据库的进程级单例管理器。
# 文件版本: 3.1.0
"""数据库管理器。

``DbManager`` 在程序启动时实例化所有已登记的 :class:`DbProvider`，并以
``{base_name: provider}`` 的形式保存。功能层通过 ``Feature._load_db(id)``
间接调用这里的 :meth:`DbManager.load`。

provider 采用显式注册表 + 动态导入：被构建裁剪掉的功能模块会触发
``ImportError`` 并被跳过，因此发布产物不需要改动这里的代码。
"""
from __future__ import annotations

import importlib
import logging
import threading
from typing import Any, Final

from .provider import DbProvider, DbProviderNotFoundError

__version__ = "3.1.0"
__author__ = "Gary"
__all__ = [
    "PROVIDER_SPECS",
    "DbManager",
    "get_db_manager",
    "init_db_manager",
]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

# 新增带数据库的功能时，在此登记 (模块路径, 类名)。
PROVIDER_SPECS: Final[tuple[tuple[str, str], ...]] = (
    ("hwklr.db.hsrdb", "HSRDb"),
)


class DbManager:
    """数据库提供者注册表。"""

    def __init__(self) -> None:
        """创建管理器并实例化所有已登记的 provider。"""
        self._providers: dict[str, DbProvider] = {}
        self._lock: threading.RLock = threading.RLock()
        self._register_builtin_providers()

    def _register_builtin_providers(self) -> None:
        """按 :data:`PROVIDER_SPECS` 动态导入并注册 provider。

        模块或类不存在（功能被裁剪）时静默跳过；provider 初始化异常只记录
        日志，不影响程序启动与其余数据库。
        """
        for module_name, class_name in PROVIDER_SPECS:
            try:
                module: Any = importlib.import_module(module_name)
                provider_cls: Any = getattr(module, class_name)
                provider: DbProvider = provider_cls()
            except ImportError:
                _LOGGER.debug(
                    "数据库 provider 不可用（可能已被裁剪）: %s",
                    module_name,
                )
                continue
            except Exception:
                _LOGGER.exception("数据库 provider 初始化失败: %s", module_name)
                continue
            try:
                self.register(provider)
            except (TypeError, ValueError):
                _LOGGER.exception("数据库 provider 注册失败: %s", module_name)

    def register(self, provider: DbProvider) -> None:
        """注册一个 provider。

        Args:
            provider: :class:`DbProvider` 实例。

        Raises:
            TypeError: ``provider`` 不是 DbProvider。
            ValueError: 同一 ``base_name`` 已注册。
        """
        if not isinstance(provider, DbProvider):
            raise TypeError("只能注册 DbProvider 实例")
        with self._lock:
            name: str = provider.base_name
            if name in self._providers:
                raise ValueError("数据库已注册: %s" % name)
            self._providers[name] = provider

    def get(self, base_name: str) -> DbProvider | None:
        """按名称查找 provider。

        Args:
            base_name: 数据库名称，例如 ``"hsr"``。

        Returns:
            找到的 provider；不存在时返回 ``None``。
        """
        with self._lock:
            return self._providers.get(str(base_name or "").strip())

    def load(self, base_name: str, id: int) -> Any:
        """读取指定数据库的记录。

        Args:
            base_name: 数据库名称。
            id: 数据库记录编号。

        Returns:
            provider 返回的 JSON 对象。

        Raises:
            DbProviderNotFoundError: 没有匹配的 provider。
            DbError: provider 加载失败时透传其数据库异常。
        """
        provider: DbProvider | None = self.get(base_name)
        if provider is None:
            raise DbProviderNotFoundError(
                "未找到数据库: %s（已注册: %s）"
                % (base_name, ", ".join(self.base_names) or "无")
            )
        return provider.load(id)

    def bank_info(self) -> list[dict[str, Any]]:
        """汇总各 provider 的展示信息。

        单个 provider 失败只记录日志并跳过，保证设置页始终可渲染。

        Returns:
            ``[{feature, version, count}, ...]``。
        """
        with self._lock:
            providers: list[DbProvider] = list(self._providers.values())
        rows: list[dict[str, Any]] = []
        for provider in providers:
            try:
                rows.extend(provider.bank_info())
            except Exception as exc:
                _LOGGER.warning(
                    "读取数据库信息失败 %s: %s",
                    provider.base_name,
                    exc,
                )
        return rows

    @property
    def base_names(self) -> tuple[str, ...]:
        """返回已注册的数据库名称。

        Returns:
            按注册顺序排列的名称元组。
        """
        with self._lock:
            return tuple(self._providers)


_MANAGER: DbManager | None = None
_MANAGER_LOCK: Final[threading.Lock] = threading.Lock()


def get_db_manager() -> DbManager:
    """返回进程级数据库管理器（首次调用时创建）。

    Returns:
        全局 :class:`DbManager` 实例。
    """
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = DbManager()
        return _MANAGER


def init_db_manager() -> DbManager:
    """重建进程级数据库管理器。

    只导入并实例化 provider，不创建数据库目录，因此目录不可写也不会
    影响程序启动。

    Returns:
        新建的 :class:`DbManager` 实例。
    """
    global _MANAGER
    with _MANAGER_LOCK:
        _MANAGER = DbManager()
        return _MANAGER
