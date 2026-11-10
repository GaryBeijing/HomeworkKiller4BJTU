# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-10 23:10
# 文件名: registry.py
# 主要用途: 管理标签页实例、启用状态、固定顺序、设置板块与关于元信息注册。
# 文件版本: 4.4.2
"""标签页注册表。"""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any, Callable, Final

from hwklr.features import extensions as extension_api

from .tagview import TagView
from .tagview.view_data import (
    ABOUT_NAME,
    SETTINGS_NAME,
    all_view_params,
    get_view_param,
    register_extension_param,
    unregister_extension_param,
)

if TYPE_CHECKING:
    from .extension_runtime import ExtensionRuntime

__version__ = "4.4.2"
__author__ = "Gary"
__all__ = ["TagRegistry"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
# “构建”固定为倒数第三的标签（构建、设置、关于）。
_BUILD_NAME: Final[str] = "构建"


class TagRegistry:
    """窗口级标签注册表。"""

    def __init__(
        self,
        universal_param: dict[str, Any],
        extensions: "ExtensionRuntime",
        enabled: Callable[[str], bool],
        set_enabled: Callable[[str, bool], None],
    ) -> None:
        """初始化注册表。

        Args:
            universal_param: 注入功能的通用参数。
            extensions: 运行期扩展注册表。
            enabled: 判断功能是否启用的回调。
            set_enabled: 设置功能启用状态的回调。
        """
        self.tags: dict[str, TagView] = {}
        self.order: list[str] = []
        self._universal_param: dict[str, Any] = universal_param
        self._extensions: "ExtensionRuntime" = extensions
        self._enabled: Callable[[str], bool] = enabled
        self._set_enabled: Callable[[str, bool], None] = set_enabled
        self._features_meta: list[dict[str, str]] = []
        # leaf lock：只保护内存结构；不在持锁时调用插件、Feature 或网络。
        self._lock: threading.RLock = threading.RLock()
        # 运行期安装串行化；加载 TagView 期间不持有 _lock，避免阻塞 /api/tags。
        self._mutation_lock: threading.RLock = threading.RLock()
        self._revision: int = 0

    def load_initial(self) -> None:
        """按合并后的注册表创建初始标签。"""
        for name in list(all_view_params()):
            try:
                self.tags[name] = TagView.load(name, self._universal_param)
            except Exception:  # 单个扩展/功能异常不应阻止整个程序启动。
                _LOGGER.exception("标签加载失败: %s", name)
                if name in self._extensions.names:
                    self._extensions.failed(name)
        self._require_core_tags()
        self.refresh_order()
        self.register_all_settings_groups()
        self.register_about_metas()

    def _require_core_tags(self) -> None:
        """确认设置与关于标签存在。

        Raises:
            RuntimeError: 缺少必需标签。
        """
        with self._lock:
            for required in (SETTINGS_NAME, ABOUT_NAME):
                if required not in self.tags:
                    raise RuntimeError("缺少必需标签: %s" % required)

    def refresh_order(self) -> list[str]:
        """按功能启用状态重新计算并校验标签顺序。

        Returns:
            最终标签名称列表。

        Raises:
            RuntimeError: 缺少设置/关于标签或顺序不合法时抛出。
        """
        self._require_core_tags()
        # _enabled 可能读取配置；在锁外计算，避免注册表锁跨越 I/O。
        # 若计算期间注册表发生变更，则重试，保证 order 基于稳定快照。
        for _ in range(4):
            with self._lock:
                names: list[str] = list(self.tags)
                revision: int = self._revision
            enabled_names: list[str] = [
                name
                for name in names
                if name not in (SETTINGS_NAME, ABOUT_NAME)
                and self._enabled(name)
            ]
            with self._lock:
                if revision != self._revision or list(self.tags) != names:
                    continue
                feature_names: list[str] = list(enabled_names)
                # 运行期插件与启动期官方功能都遵循 ViewParam.order；
                # sorted 稳定，因此同 order 保持注册先后。
                feature_names.sort(key=lambda name: self.tags[name].order)
                # “构建”始终排在功能标签最后，从而位于 构建 / 设置 / 关于 的倒数第三。
                if _BUILD_NAME in feature_names:
                    feature_names.remove(_BUILD_NAME)
                    feature_names.append(_BUILD_NAME)
                order: list[str] = feature_names + [SETTINGS_NAME, ABOUT_NAME]
                if order[-1] != ABOUT_NAME or order[-2] != SETTINGS_NAME:
                    raise RuntimeError("标签顺序不合法：设置必须倒数第二、关于必须最后")
                if _BUILD_NAME in order and order[-3] != _BUILD_NAME:
                    raise RuntimeError("标签顺序不合法：构建必须倒数第三")
                self.order = order
                self._features_meta = [
                    {"name": name, "description": self.tags[name].description}
                    for name in feature_names
                ]
                return list(order)
        raise RuntimeError("标签注册表在刷新期间持续变化")

    @property
    def features_meta(self) -> list[dict[str, str]]:
        """返回应用元信息中的功能列表副本。"""
        with self._lock:
            return [dict(item) for item in self._features_meta]

    def order_names(self) -> list[str]:
        """返回标签顺序的线程安全副本。"""
        with self._lock:
            return list(self.order)

    def tag_map(self) -> dict[str, TagView]:
        """返回标签映射的线程安全副本。"""
        with self._lock:
            return dict(self.tags)

    def register_all_settings_groups(self) -> None:
        """把所有功能标签的设置组注册到设置页。"""
        with self._lock:
            settings_tag: TagView | None = self.tags.get(SETTINGS_NAME)
            items: dict[str, TagView] = dict(self.tags)
        if settings_tag is None:
            return
        group_names: list[str] = [
            name
            for name in items
            if name not in (SETTINGS_NAME, ABOUT_NAME)
        ]
        if _BUILD_NAME in group_names:
            group_names.remove(_BUILD_NAME)
            group_names.append(_BUILD_NAME)
        for name in group_names:
            self.register_settings_group(name, items[name])

    def register_settings_group(self, name: str, tag: TagView) -> None:
        """把一个标签的设置组绑定启用开关并注册到设置页。

        Args:
            name: 标签名。
            tag: 标签页实例。
        """
        with self._lock:
            settings_tag: TagView | None = self.tags.get(SETTINGS_NAME)
        if settings_tag is None:
            return
        try:
            group = tag.settings_group
        except Exception:  # 第三方扩展的设置组异常不应拖垮设置页。
            _LOGGER.exception("读取设置组失败: %s", name)
            return
        if not group.enabled_editable:
            group.bind_enabled(
                lambda: self._enabled(name),
                lambda enabled: self._set_enabled(name, enabled),
                editable=True,
            )
        if group.field_specs or group.enabled_editable:
            settings_tag.register_settings_field(group)

    def register_about_metas(self) -> None:
        """把所有功能的元信息注册到“关于”页。"""
        with self._lock:
            about_tag: TagView | None = self.tags.get(ABOUT_NAME)
            items: list[tuple[str, TagView]] = list(self.tags.items())
        if about_tag is None:
            return
        register: Any = getattr(about_tag.feature, "register_meta", None)
        if not callable(register):
            return
        for name, tag in items:
            if name in (SETTINGS_NAME, ABOUT_NAME):
                continue
            try:
                register(tag.feature.about_meta)
            except Exception:  # 第三方扩展缺少元信息时不影响其它功能。
                _LOGGER.exception("注册关于元信息失败: %s", name)

    def install_runtime(self, info: Any, temporary: bool = False) -> TagView:
        """把运行期加载的扩展安装为标签页。

        Args:
            info: 扩展信息。
            temporary: 是否为“测试插件”临时加载。

        Returns:
            新建的标签页。

        Raises:
            RuntimeError: 标签名保留或与官方功能重名。
        """
        if info.tab_name in (SETTINGS_NAME, ABOUT_NAME):
            raise RuntimeError("扩展标签名不能使用保留名称")
        with self._mutation_lock:
            with self._lock:
                existing: TagView | None = self.tags.get(info.tab_name)
            if existing is not None and info.tab_name not in self._extensions.names:
                raise RuntimeError("标签名已存在：%s" % info.tab_name)
            previous_param = get_view_param(info.tab_name)
            # 参数注册与 TagView.load 可能执行插件代码，必须在注册表锁外完成。
            if existing is not None:
                unregister_extension_param(info.tab_name)
            self._extensions.adopt(info, temporary=temporary)
            try:
                tag: TagView = TagView.load(info.tab_name, self._universal_param)
            except Exception:
                # 热替换失败时恢复旧参数，避免旧标签失去路由元信息。
                if previous_param is not None:
                    register_extension_param(previous_param)
                else:
                    unregister_extension_param(info.tab_name)
                raise
            # 原子替换标签；/api/tags 只会看到旧标签或新标签，不会看到半状态。
            with self._lock:
                if existing is not None:
                    self.tags.pop(info.tab_name, None)
                self.tags[info.tab_name] = tag
                self._revision += 1
            if existing is not None:
                self._remove_settings_group(existing)
            self.register_settings_group(info.tab_name, tag)
            with self._lock:
                about_tag: TagView | None = self.tags.get(ABOUT_NAME)
            register_meta: Any = (
                getattr(about_tag.feature, "register_meta", None)
                if about_tag is not None
                else None
            )
            if callable(register_meta):
                try:
                    register_meta(tag.feature.about_meta)
                except Exception:
                    _LOGGER.exception("注册扩展关于元信息失败: %s", info.tab_name)
            extension_api.invalidate_extension_cache()
            self.refresh_order()
            return tag

    def _remove_settings_group(self, tag: TagView) -> None:
        """从设置页移除标签的设置组。

        Args:
            tag: 即将被替换的标签页。
        """
        with self._lock:
            settings_tag: TagView | None = self.tags.get(SETTINGS_NAME)
        remove: Any = (
            getattr(settings_tag.feature, "unregister_group", None)
            if settings_tag is not None
            else None
        )
        if callable(remove):
            remove(tag.settings_group.group_id)

    def payload(self) -> list[dict[str, Any]]:
        """返回供前端渲染的标签列表（含必要设置状态）。

        Returns:
            按最终顺序排列的标签描述。
        """
        self.refresh_order()
        with self._lock:
            snapshot: list[tuple[str, TagView]] = [
                (name, self.tags[name])
                for name in self.order
                if name in self.tags
            ]
        payload: list[dict[str, Any]] = []
        for name, tag in snapshot:
            group = tag.settings_group
            missing: list[str] = group.missing_labels() if group else []
            item: dict[str, Any] = tag.describe()
            item["settings_ok"] = bool(group.is_complete()) if group else True
            item["settings_group"] = group.group_id if group else ""
            item["missing_settings"] = missing
            # 如果用户名缺失，优先跳到“通用”板块；否则跳到功能自己的板块。
            item["settings_target"] = (
                "general"
                if any("用户名" in label for label in missing)
                else (group.group_id if group else "")
            )
            payload.append(item)
        return payload

    def clear(self) -> None:
        """停止所有标签功能。"""
        with self._lock:
            tags: list[TagView] = list(self.tags.values())
            self.tags.clear()
            self.order.clear()
            self._features_meta.clear()
            self._revision += 1
        for tag in tags:
            try:
                tag.stop()
            except Exception:
                _LOGGER.exception("停止标签失败: %s", tag.name)

    def shutdown(self) -> None:
        """窗口关闭时调用每个功能的 shutdown，不触发 stop/取消。"""
        with self._lock:
            tags: list[TagView] = list(self.tags.values())
        for tag in tags:
            shutdown = getattr(tag.feature, "shutdown", None)
            if not callable(shutdown):
                continue
            try:
                shutdown()
            except Exception:
                _LOGGER.exception("关闭功能失败: %s", tag.name)
