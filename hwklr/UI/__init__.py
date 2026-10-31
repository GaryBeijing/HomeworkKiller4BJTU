# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 文件名: __init__.py
# 主要用途: 封装 pywebview 核心窗口 WindowView 与 JS 桥接对象 BridgeApi。
# 文件版本: 1.0.0
"""UI 窗口层。

入口只需::

    window = WindowView()
    window.run()

标签页由 :class:`hwklr.UI.tagview.TagView` 抽象；窗口负责标签顺序约束、
本地 HTTP 服务、pywebview 窗口创建与桥接分发。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Final

import webview

from hwklr import (
    APP_AUTHORS,
    APP_DESCRIPTION,
    APP_DISCLAIMER,
    APP_NAME,
    APP_TITLE,
)
from hwklr import __version__ as APP_VERSION
from hwklr.config import load_config
from hwklr.features import failure

from .server import UiHttpServer
from .tagview import TagView
from .tagview.view_data import ABOUT_NAME, SETTINGS_NAME, VIEW_PARAMS

__version__ = "1.0.0"
__author__ = "Gary"
__all__ = ["BridgeApi", "WindowView"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_UI_DIR: Final[Path] = Path(__file__).resolve().parent
_PAGE_DATA_DIR: Final[Path] = _UI_DIR / "page_data"
_VIEW_DATA_DIR: Final[Path] = _UI_DIR / "tagview" / "view_data"
_WINDOW_BACKGROUND: Final[str] = "#2f3ab2"


class BridgeApi:
    """暴露给前端 ``window.pywebview.api`` 的对象。

    前端只调用 :meth:`call`，由窗口层把动作转交给当前标签的功能实例。
    这样各标签无需各自注册不同桥接函数，保持 UI 与功能解耦。
    """

    def __init__(self, window_view: "WindowView") -> None:
        """初始化桥接对象。

        Args:
            window_view: 所属窗口。
        """
        self._window_view: WindowView = window_view

    def call(
        self,
        tag: str,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """转发一次功能调用。

        Args:
            tag: 标签名称（功能名称）。
            method: 功能动作名称。
            params: 动作参数。

        Returns:
            统一格式的结果字典。
        """
        return self._window_view.bridge_call(tag, method, params)

    def get_tags(self) -> list[dict[str, Any]]:
        """返回标签页元数据列表。

        Returns:
            按最终顺序排列的标签描述。
        """
        return self._window_view.tags_payload()

    def get_meta(self) -> dict[str, Any]:
        """返回应用元信息。

        Returns:
            应用名称、版本、作者、端口等信息。
        """
        return self._window_view.meta_payload()


class WindowView:
    """核心窗口类。

    负责标签注册、顺序约束、本地服务生命周期与 pywebview 窗口。
    """

    def __init__(
        self,
        title: str = APP_TITLE,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        """初始化窗口与所有标签页。

        Args:
            title: 窗口标题。
            width: 窗口宽度；``None`` 时读取配置。
            height: 窗口高度；``None`` 时读取配置。
        """
        self._config: dict[str, Any] = load_config()
        self._ui_config: dict[str, Any] = self._config.get("ui", {})
        self._title: str = title
        self._width: int = int(width or self._ui_config.get("width", 1100))
        self._height: int = int(height or self._ui_config.get("height", 720))
        self._min_width: int = int(self._ui_config.get("min_width", 900))
        self._min_height: int = int(self._ui_config.get("min_height", 620))
        self._context: dict[str, Any] = {"port": 0}
        self._meta: dict[str, Any] = self._build_meta()
        self._tags: dict[str, TagView] = {}
        self._order: list[str] = []
        self._active_name: str | None = None
        self._server: UiHttpServer | None = None
        self._window: webview.Window | None = None

        # 步骤 1：按注册表创建标签（功能实例在此注入通用参数）。
        universal_param: dict[str, Any] = {
            "context": self._context,
            "app_meta": self._meta,
        }
        for name in VIEW_PARAMS:
            self._tags[name] = TagView.load(name, universal_param)

        # 步骤 2：强制“设置倒数第二、关于最后”的标签顺序。
        self._order = self._resolve_order()
        self._meta["features"] = [
            {"name": name, "description": self._tags[name].description}
            for name in self._order
            if name not in (SETTINGS_NAME, ABOUT_NAME)
        ]

    def _build_meta(self) -> dict[str, Any]:
        """构建应用元信息。

        Returns:
            应用名称、标题、版本、作者、简介、声明与端口。
        """
        return {
            "name": APP_NAME,
            "title": APP_TITLE,
            "version": APP_VERSION,
            "authors": list(APP_AUTHORS),
            "description": APP_DESCRIPTION,
            "disclaimer": APP_DISCLAIMER,
            "features": [],
            "port": 0,
        }

    def _resolve_order(self) -> list[str]:
        """计算并校验标签顺序。

        Returns:
            最终标签名称列表。

        Raises:
            RuntimeError: 缺少设置/关于标签或顺序不合法时抛出。
        """
        names: list[str] = list(VIEW_PARAMS.keys())
        missing: list[str] = [
            name for name in (SETTINGS_NAME, ABOUT_NAME) if name not in names
        ]
        if missing:
            raise RuntimeError("缺少必需标签: %s" % ", ".join(missing))
        feature_names: list[str] = [
            name for name in names if name not in (SETTINGS_NAME, ABOUT_NAME)
        ]
        order: list[str] = feature_names + [SETTINGS_NAME, ABOUT_NAME]
        # 双重校验：无论注册表如何调整，最后两个标签的位置必须固定。
        if order[-1] != ABOUT_NAME or order[-2] != SETTINGS_NAME:
            raise RuntimeError("标签顺序不合法：设置必须倒数第二、关于必须最后")
        return order

    @property
    def order(self) -> list[str]:
        """返回标签顺序副本。

        Returns:
            标签名称列表。
        """
        return list(self._order)

    @property
    def tags(self) -> dict[str, TagView]:
        """返回标签映射副本。

        Returns:
            名称到 :class:`TagView` 的字典。
        """
        return dict(self._tags)

    @property
    def active_tag(self) -> TagView | None:
        """返回当前激活的标签。

        Returns:
            当前标签；未激活时为 ``None``。
        """
        if self._active_name is None:
            return None
        return self._tags.get(self._active_name)

    def tags_payload(self) -> list[dict[str, Any]]:
        """返回供前端渲染的标签列表。

        Returns:
            按最终顺序排列的标签描述。
        """
        return [self._tags[name].describe() for name in self._order]

    def meta_payload(self) -> dict[str, Any]:
        """返回供前端读取的应用元信息。

        Returns:
            元信息字典，包含实际监听端口。
        """
        meta: dict[str, Any] = dict(self._meta)
        meta["features"] = list(self._meta.get("features", []))
        meta["port"] = int(self._context.get("port", 0))
        return meta

    def bridge_call(
        self,
        tag: str,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """把前端调用路由到指定标签的功能实例。

        Args:
            tag: 标签名称。
            method: 动作名称。
            params: 动作参数。

        Returns:
            统一格式的结果字典。
        """
        tagview: TagView | None = self._tags.get(tag)
        if tagview is None:
            return failure("未知标签: %s" % tag)
        if not isinstance(method, str) or not method or method.startswith("_"):
            return failure("非法动作: %s" % method)
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return failure("动作参数必须是对象")
        try:
            return tagview.call(method, params)
        except Exception as exc:  # 兜底，保证前端拿到可读错误。
            _LOGGER.exception("桥接调用失败 tag=%s method=%s", tag, method)
            return failure("调用失败: %s" % exc)

    def start_server(self) -> int:
        """启动本地 UI 服务。

        Returns:
            实际监听端口。

        Raises:
            OSError: 找不到空闲端口时抛出。
        """
        if self._server is not None:
            return self._server.port
        server_config: dict[str, Any] = self._config.get("server", {})
        preferred_port: int = int(server_config.get("preferred_port", 49152))
        server: UiHttpServer = UiHttpServer(
            page_dir=_PAGE_DATA_DIR,
            view_data_dir=_VIEW_DATA_DIR,
            preferred_port=preferred_port,
            tags_provider=self.tags_payload,
            meta_provider=self.meta_payload,
        )
        port: int = server.start()
        self._server = server
        self._context["port"] = port
        return port

    def stop_server(self) -> None:
        """停止本地 UI 服务。"""
        if self._server is not None:
            self._server.stop()
            self._server = None
        self._context["port"] = 0

    def activate_tagview(self, tagview: TagView) -> None:
        """切换到指定标签页。

        Args:
            tagview: 目标标签页实例。

        Raises:
            ValueError: 标签不属于当前窗口时抛出。
        """
        canonical: TagView | None = self._tags.get(tagview.name)
        if canonical is None:
            raise ValueError("标签不属于当前窗口: %s" % tagview.name)
        # 使用窗口内注册的实例，避免外部重复构造同名标签导致状态不一致。
        tagview = canonical
        if self._active_name == tagview.name:
            return
        previous: TagView | None = self.active_tag
        if previous is not None:
            previous.stop()
        self._active_name = tagview.name
        tagview.start()
        window: webview.Window | None = self._window
        if window is None and webview.windows:
            # 兼容外部自行 create_window 后调用本方法的场景。
            window = webview.windows[0]
        if window is not None:
            # 前端 App.activate 幂等；此处用于 Python 侧主动切换。
            script: str = "window.App && window.App.activate(%s);" % json.dumps(
                tagview.name, ensure_ascii=False
            )
            window.evaluate_js(script)

    def _on_window_loaded(self) -> None:
        """窗口加载完成后激活第一个标签。"""
        if not self._order:
            return
        try:
            self.activate_tagview(self._tags[self._order[0]])
        except Exception:  # 加载阶段的异常不应导致窗口直接退出。
            _LOGGER.exception("激活默认标签失败")

    def run(self) -> None:
        """启动本地服务与 pywebview 窗口（必须在主线程调用）。"""
        self.start_server()
        try:
            port: int = self._context.get("port", 0)
            self._window = webview.create_window(
                title=self._title,
                url="http://127.0.0.1:%d/" % port,
                js_api=BridgeApi(self),
                width=self._width,
                height=self._height,
                min_size=(self._min_width, self._min_height),
                resizable=True,
                background_color=_WINDOW_BACKGROUND,
                text_select=True,
            )
            # 页面加载完成后同步 Python 侧的活动标签，并触发一次 activate_tagview。
            self._window.events.loaded += self._on_window_loaded
            webview.start(debug=bool(self._ui_config.get("debug", False)))
        finally:
            self._window = None
            self.stop_server()
