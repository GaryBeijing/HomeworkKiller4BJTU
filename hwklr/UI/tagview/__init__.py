# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-10 10:00
# 文件名: __init__.py
# 主要用途: 定义标签页抽象 TagView，统一管理功能实例、设置组、官方/扩展 HTML/CSS/JS 资源与桥接调用。
# 文件版本: 4.4.0
"""标签页抽象。

每个标签页 = 一套前端资源（HTML/CSS/JS）+ 一个 :class:`Feature` 实例。
窗口层只持有 :class:`TagView`，通过 :meth:`TagView.load` 按名称创建。
"""
from __future__ import annotations

import abc
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from hwklr.features import Feature

from .view_data import SETTINGS_NAME, ViewParam, get_view_param

if TYPE_CHECKING:
    from hwklr.features.settings import FeatureSettingsGroup

__version__ = "3.0.0"
__author__ = "Gary"
__all__ = ["SettingsTagView", "TagView", "TagViewBase", "ViewParam", "VIEW_DATA_DIR"]

VIEW_DATA_DIR: Final[Path] = Path(__file__).resolve().parent / "view_data"


class TagViewBase(abc.ABC):
    """标签页抽象接口。

    所有标签页必须提供只读的 :attr:`settings_group`，窗口层会在启动时
    把这些设置组注册到设置页。
    """

    @property
    @abc.abstractmethod
    def settings_group(self) -> "FeatureSettingsGroup":
        """返回该标签的设置组。

        Returns:
            功能设置组。
        """
        raise NotImplementedError


class TagView(TagViewBase):
    """单个标签页。

    负责：
    - 持有并启动对应功能实例；
    - 提供该标签的 HTML/CSS/JS 资源 URL；
    - 将前端的动作调用转发给功能实例。
    """

    def __init__(self, param: ViewParam, feature: Feature) -> None:
        """初始化标签页。

        Args:
            param: 标签页静态参数。
            feature: 对应的功能实例。
        """
        self._param: ViewParam = param
        self._feature: Feature = feature
        # 扩展资源位于 extension/<id>/，官方标签使用 view_data/。
        self._resource_root: Path = (
            Path(param.resource_root) if param.resource_root else VIEW_DATA_DIR
        )
        self._html_path: Path = self._resource_root / param.html
        self._css_paths: tuple[Path, ...] = tuple(
            self._resource_root / item for item in param.css
        )
        self._js_paths: tuple[Path, ...] = tuple(
            self._resource_root / item for item in param.js
        )
        missing: list[Path] = [
            path for path in (self._html_path, *self._css_paths, *self._js_paths)
            if not path.is_file()
        ]
        if missing:
            raise FileNotFoundError(
                "标签 %s 缺少资源文件: %s"
                % (param.function_name, ", ".join(str(path) for path in missing))
            )

    @classmethod
    def load(
        cls,
        name: str,
        universal_param: dict[str, Any] | None = None,
    ) -> "TagView":
        """按名称创建标签页实例。

        Args:
            name: 功能名称，如 ``"高铁纵横"``。
            universal_param: 注入功能的通用参数。

        Returns:
            新建的 :class:`TagView`。

        Raises:
            KeyError: 名称不存在时抛出。
            FileNotFoundError: 标签资源缺失时抛出。
        """
        param: ViewParam | None = get_view_param(name)
        if param is None:
            raise KeyError("未知功能: %s" % name)
        feature: Feature = param.feature_cls(universal_param or {})
        if cls is TagView and name == SETTINGS_NAME:
            return SettingsTagView(param, feature)
        return cls(param, feature)

    @property
    def name(self) -> str:
        """返回功能名称。

        Returns:
            功能名称。
        """
        return self._param.function_name

    @property
    def title(self) -> str:
        """返回标签显示标题。

        Returns:
            标签标题。
        """
        return self._param.title

    @property
    def description(self) -> str:
        """返回标签说明。

        Returns:
            标签说明文本。
        """
        return self._param.description

    @property
    def feature(self) -> Feature:
        """返回持有的功能实例。

        Returns:
            功能实例。
        """
        return self._feature

    @property
    def settings_group(self) -> "FeatureSettingsGroup":
        """返回该标签必须提供的只读设置组。

        这是 TagView 的抽象只读属性：所有功能都必须实现
        ``Feature.settings_group``，窗口启动时会把非设置标签的设置组注册到设置页。

        Returns:
            功能设置组。
        """
        return self._feature.settings_group

    @property
    def html_path(self) -> Path:
        """返回标签 HTML 文件路径。

        Returns:
            HTML 绝对路径。
        """
        return self._html_path

    def describe(self) -> dict[str, Any]:
        """返回供前端渲染标签栏的元数据。

        Returns:
            含名称、标题、HTML/CSS/JS URL 的字典。
        """
        base: str = self._param.base_url or "/view_data/"
        actions: list[dict[str, Any]] = []
        for spec in self._feature.action_specs():
            actions.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "risk": spec.risk,
                    "params": [
                        {
                            "name": param.name,
                            "required": param.required,
                            "default": param.default,
                            "choices": list(param.choices),
                        }
                        for param in spec.params
                    ],
                }
            )
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "html_url": base + self._param.html,
            "css_urls": [base + item for item in self._param.css],
            "js_urls": [base + item for item in self._param.js],
            "actions": actions,
        }

    def start(self) -> None:
        """启动标签对应功能。"""
        self._feature.start()

    def stop(self) -> None:
        """停止标签对应功能。"""
        self._feature.stop()

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """把前端动作转发给功能实例。

        Args:
            method: 动作名称。
            params: 动作参数。

        Returns:
            功能返回的统一结果字典。

        Raises:
            ValueError: 动作名非法时抛出。
        """
        if not method or method.startswith("_"):
            raise ValueError("非法动作: %s" % method)
        return self._feature.dispatch(method, params)

    def __repr__(self) -> str:
        """返回调试用字符串表示。

        Returns:
            标签名称。
        """
        return "TagView(%s)" % json.dumps(self.name, ensure_ascii=False)


class SettingsTagView(TagView):
    """设置标签页。

    在通用 TagView 基础上额外提供 :meth:`register_settings_field`，
    供 WindowView 注册其他功能的设置板块。
    """

    def register_settings_field(self, group: "FeatureSettingsGroup") -> None:
        """把功能设置组注册到设置页。

        Args:
            group: 功能设置组。

        Raises:
            TypeError: 设置功能未实现注册接口时抛出。
        """
        register = getattr(self._feature, "register_group", None)
        if not callable(register):
            raise TypeError("设置标签的功能未实现 register_group")
        register(group)
