# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-10 10:00
# 文件名: about.py
# 主要用途: 实现“关于”标签页功能：注册软件与各功能/插件的元信息，并提供 AboutMetadataGroup。
# 文件版本: 4.4.0
"""关于功能与元信息组。

V3 起，每个功能通过只读属性 ``about_meta`` 返回一个
:class:`AboutMetadataGroup`；窗口层把所有功能的元信息注册到
:class:`AboutFeature`，最终由“关于”页统一展示。
"""
from __future__ import annotations

from typing import Any, Final

from hwklr import APP_AUTHORS, APP_NAME, __version__ as APP_VERSION
from hwklr.contracts import ActionSpec
from hwklr.feature_specs import FeatureSpec
from hwklr.features.base import ApiResult, Feature, failure, success
from hwklr.features.versions import format_app_version, format_plugin_version

from .settings import FeatureSettingsGroup

__version__ = "4.4.0"
__author__ = "Gary"
__all__ = ["AboutFeature", "AboutMetadataGroup", "about_meta_from_spec"]

_SOFTWARE_KEY: Final[str] = "__software__"


class AboutMetadataGroup:
    """“关于”页中的一条软件/插件元信息。

    与 :class:`FeatureSettingsGroup` 类似，本类只描述数据与展示规则，
    不负责页面渲染；官方包名末尾会自动追加 ``(Offical)``。
    """

    def __init__(
        self,
        name: str,
        package: str,
        author: str,
        version: str,
        update_date: str = "",
        official: bool = False,
        feature_key: str = "",
        description: str = "",
        is_software: bool = False,
    ) -> None:
        """初始化元信息组。

        Args:
            name: 插件名或软件名。
            package: 插件包名。
            author: 作者。
            version: 原始版本号。
            update_date: 更新日期。
            official: 是否为官方插件。
            feature_key: 对应功能标签名，用于读取启用状态。
            description: 简介。
            is_software: 是否代表软件本体（使用软件版本格式）。
        """
        self.name: str = str(name or "")
        self.package: str = str(package or "")
        self.author: str = str(author or "")
        self.version: str = str(version or "")
        self.update_date: str = str(update_date or "")
        self.official: bool = bool(official)
        self.feature_key: str = str(feature_key or "")
        self.description: str = str(description or "")
        self.is_software: bool = bool(is_software)

    @property
    def version_display(self) -> str:
        """返回展示用版本号。

        Returns:
            软件使用 ``vA.B.PatchC-bD``，插件使用 ``A.BpC-bD``。
        """
        if self.is_software:
            return format_app_version(self.version)
        return format_plugin_version(self.version)

    @property
    def package_display(self) -> str:
        """返回展示用包名。

        Returns:
            官方插件末尾追加 ``(Offical)``。
        """
        if self.is_software:
            return self.package
        return "%s%s" % (self.package, " (Offical)" if self.official else "")

    def payload(self, enabled: bool | None = None) -> dict[str, Any]:
        """返回供“关于”页渲染的数据。

        Args:
            enabled: 启用状态；``None`` 时按当前注册值。

        Returns:
            可 JSON 序列化的字典。
        """
        return {
            "name": self.name,
            "package": self.package,
            "package_display": self.package_display,
            "author": self.author,
            "version": self.version,
            "version_display": self.version_display,
            "update_date": self.update_date,
            "official": self.official,
            "enabled": True if self.is_software else bool(enabled),
            "description": self.description,
            "is_software": self.is_software,
            "feature_key": self.feature_key,
        }


def about_meta_from_spec(spec: FeatureSpec, version: str) -> AboutMetadataGroup:
    """用 FeatureSpec 的元信息构造官方功能 AboutMetadataGroup。

    Args:
        spec: 官方功能描述。
        version: 功能模块版本号。

    Returns:
        关于页元信息组。
    """
    meta = spec.meta
    if meta is None:
        return AboutMetadataGroup(
            name=spec.name,
            package=spec.stable_id.upper(),
            author="",
            version=version,
            official=True,
            feature_key=spec.name,
            description=spec.description,
        )
    return AboutMetadataGroup(
        name=spec.name,
        package=meta.package,
        author=meta.author,
        version=version,
        update_date=meta.update_date,
        official=meta.official,
        feature_key=spec.name,
        description=meta.description or spec.description,
    )


class AboutFeature(Feature):
    """“关于”标签页功能。"""

    @classmethod
    def action_specs(cls) -> tuple[ActionSpec, ...]:
        """返回关于页动作声明。"""
        return (ActionSpec("get_meta"),)

    def __init__(self, universal_param: dict[str, Any]) -> None:
        """初始化关于功能并注册软件本体元信息。

        Args:
            universal_param: 窗口层注入的通用参数。
        """
        super().__init__(universal_param)
        self._metas: list[AboutMetadataGroup] = [self._build_software_meta()]
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

    @staticmethod
    def _build_software_meta() -> AboutMetadataGroup:
        """构建软件本体元信息。

        Returns:
            软件元信息组。
        """
        return AboutMetadataGroup(
            name=APP_NAME,
            package="HWKLR",
            author="Gary",
            version=APP_VERSION,
            update_date="2026-11-03",
            official=True,
            feature_key=_SOFTWARE_KEY,
            description="HomeworkKiller4BJTU 软件本体。",
            is_software=True,
        )

    @property
    def settings_group(self) -> FeatureSettingsGroup:
        """返回空的设置组。

        Returns:
            无字段的设置组。
        """
        return self._settings_group

    @property
    def about_meta(self) -> AboutMetadataGroup:
        """返回软件本体元信息。

        Returns:
            软件元信息组。
        """
        return self._metas[0]

    def register_meta(self, meta: AboutMetadataGroup) -> None:
        """注册一个功能的元信息。

        Args:
            meta: 功能元信息组；同名项会被覆盖。
        """
        for index, existing in enumerate(self._metas):
            if existing.name == meta.name:
                self._metas[index] = meta
                return
        self._metas.append(meta)

    @property
    def metas(self) -> list[AboutMetadataGroup]:
        """返回所有元信息副本。

        Returns:
            元信息列表（第一项为软件本体）。
        """
        return list(self._metas)

    def _enabled_for(self, meta: AboutMetadataGroup) -> bool:
        """读取一条插件元信息的当前启用状态。

        Args:
            meta: 元信息组。

        Returns:
            启用返回 ``True``；软件本体恒为 ``True``。
        """
        if meta.is_software:
            return True
        # 延迟导入，避免 features 包初始化期形成循环。
        from hwklr.features.extensions import is_feature_enabled

        return is_feature_enabled(meta.feature_key or meta.name)

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
        """返回应用元信息与插件列表。

        Args:
            params: 未使用的动作参数。

        Returns:
            应用名称、版本、作者、简介、声明、功能列表与插件元信息。
        """
        meta: Any = self._universal_param.get("app_meta") or {}
        if not isinstance(meta, dict):
            meta = {}
        result: dict[str, Any] = dict(meta)
        software: AboutMetadataGroup = self._metas[0]
        plugins: list[dict[str, Any]] = [
            item.payload(self._enabled_for(item))
            for item in self._metas[1:]
        ]
        result.update({
            "software": software.payload(True),
            "version_display": software.version_display,
            "authors": list(APP_AUTHORS),
            "plugins": plugins,
        })
        return success(result)
