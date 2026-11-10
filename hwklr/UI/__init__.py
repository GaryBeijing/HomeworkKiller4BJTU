# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-10 10:00
# 文件名: __init__.py
# 主要用途: 封装 pywebview 核心窗口 WindowView、运行期扩展注册、数据库管理器初始化、关于元信息注册与 JS 桥接对象 BridgeApi。
# 文件版本: 4.4.0
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
import urllib.parse
from pathlib import Path
from typing import Any, Final

import webview

from hwklr import db
from hwklr import (
    APP_AUTHORS,
    APP_DESCRIPTION,
    APP_DISCLAIMER,
    APP_ICON,
    APP_NAME,
    APP_TITLE,
)
from hwklr import __version__ as APP_VERSION
from hwklr.config import load_config
from hwklr.contracts import ErrorCode
from hwklr.features import extensions as extension_api
from hwklr.features import failure

from .server import UiHttpServer
from .tagview import TagView
from .tagview.view_data import (
    ABOUT_NAME,
    SETTINGS_NAME,
    ViewParam,
    all_view_params,
    register_extension_param,
    unregister_extension_param,
)

__version__ = "4.0.1"
__author__ = "Gary"
__all__ = ["BridgeApi", "WindowView"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_UI_DIR: Final[Path] = Path(__file__).resolve().parent
_PAGE_DATA_DIR: Final[Path] = _UI_DIR / "page_data"
_VIEW_DATA_DIR: Final[Path] = _UI_DIR / "tagview" / "view_data"
# 4.0.1 起“构建”固定为倒数第三的标签（构建、设置、关于）。
_BUILD_NAME: Final[str] = "构建"
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
        self._temporary_extensions: set[str] = set()
        self._extension_names: set[str] = set()
        self._extension_dirs: dict[str, Path] = {}
        self._extension_errors: list[str] = []
        # #数据库：只实例化并注册 provider，不创建目录，失败也不阻止启动。
        try:
            self._db_manager: db.DbManager = db.init_db_manager()
        except Exception:
            _LOGGER.exception("数据库管理器初始化失败，继续启动")
            self._db_manager = db.get_db_manager()
        self._universal_param: dict[str, Any] = {
            "context": self._context,
            "app_meta": self._meta,
            "dialogs": {
                "pick_directory": self._pick_directory,
                "pick_file": self._pick_file,
            },
            "extensions": {
                "register_dir": self.register_extension_dir,
            },
        }

        # 步骤 0：扫描 extension/ 并把可用扩展登记为运行期标签参数。
        self._load_installed_extensions()

        # 步骤 1：按合并后的注册表创建标签（功能实例在此注入通用参数）。
        for name in list(all_view_params()):
            try:
                self._tags[name] = TagView.load(name, self._universal_param)
            except Exception:  # 单个扩展/功能异常不应阻止整个程序启动。
                _LOGGER.exception("标签加载失败: %s", name)
                if name in self._extension_names:
                    self._extension_names.discard(name)
                    unregister_extension_param(name)
                    self._extension_errors.append("%s：标签加载失败" % name)
        for required in (SETTINGS_NAME, ABOUT_NAME):
            if required not in self._tags:
                raise RuntimeError("缺少必需标签: %s" % required)

        # 步骤 2：强制“设置倒数第二、关于最后”的标签顺序。
        self._refresh_order()

        # 步骤 3：把各标签的只读设置组注册到设置标签。
        settings_tag: TagView | None = self._tags.get(SETTINGS_NAME)
        if settings_tag is not None:
            group_names: list[str] = [
                name
                for name in self._tags
                if name not in (SETTINGS_NAME, ABOUT_NAME)
            ]
            # “构建”的设置板块始终放在最后。
            if _BUILD_NAME in group_names:
                group_names.remove(_BUILD_NAME)
                group_names.append(_BUILD_NAME)
            for name in group_names:
                self._register_settings_group(name, self._tags[name])

        # 步骤 4：把各功能的关于元信息注册到“关于”页。
        self._register_about_metas()

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

    def _refresh_order(self) -> list[str]:
        """按功能启用状态重新计算并校验标签顺序。

        Returns:
            最终标签名称列表。

        Raises:
            RuntimeError: 缺少设置/关于标签或顺序不合法时抛出。
        """
        missing: list[str] = [
            name
            for name in (SETTINGS_NAME, ABOUT_NAME)
            if name not in self._tags
        ]
        if missing:
            raise RuntimeError("缺少必需标签: %s" % ", ".join(missing))
        feature_names: list[str] = [
            name
            for name in self._tags
            if name not in (SETTINGS_NAME, ABOUT_NAME)
            and self._is_feature_enabled(name)
        ]
        # “构建”始终排在功能标签最后，从而位于 构建 / 设置 / 关于 的倒数第三。
        if _BUILD_NAME in feature_names:
            feature_names.remove(_BUILD_NAME)
            feature_names.append(_BUILD_NAME)
        order: list[str] = feature_names + [SETTINGS_NAME, ABOUT_NAME]
        # 双重校验：无论注册表如何调整，最后三个标签的位置必须固定。
        if order[-1] != ABOUT_NAME or order[-2] != SETTINGS_NAME:
            raise RuntimeError("标签顺序不合法：设置必须倒数第二、关于必须最后")
        if _BUILD_NAME in order and order[-3] != _BUILD_NAME:
            raise RuntimeError("标签顺序不合法：构建必须倒数第三")
        self._order = order
        self._meta["features"] = [
            {"name": name, "description": self._tags[name].description}
            for name in feature_names
        ]
        return order

    def _is_feature_enabled(self, name: str) -> bool:
        """判断功能当前是否应显示在标签栏。

        Args:
            name: 功能标签名。

        Returns:
            启用返回 ``True``；本次运行临时加载的扩展恒为启用。
        """
        if name in self._temporary_extensions:
            return True
        return extension_api.is_feature_enabled(name)

    def _resolve_extension_dir(self, extension_id: str) -> Path | None:
        """按扩展 ID 返回前端资源根目录。

        Args:
            extension_id: 扩展目录名（已 URL 解码）。

        Returns:
            扩展根目录；未注册时返回 ``None``。
        """
        path: Path | None = self._extension_dirs.get(str(extension_id or ""))
        return path if path is not None else None

    def _load_installed_extensions(self) -> None:
        """扫描 extension/ 并登记可用扩展的标签参数。"""
        infos, errors = extension_api.scan_installed_extensions()
        self._extension_errors = list(errors)
        for info in infos:
            if info.tab_name in all_view_params() or info.tab_name in self._extension_names:
                self._extension_errors.append(
                    "%s：扩展标签名与现有功能重复" % info.tab_name
                )
                continue
            self._extension_names.add(info.tab_name)
            self._extension_dirs[info.id] = info.path
            register_extension_param(self._extension_view_param(info))

    @staticmethod
    def _extension_view_param(info: Any) -> ViewParam:
        """把扩展信息转换为标签参数。

        Args:
            info: :class:`hwklr.features.extensions.ExtensionInfo`。

        Returns:
            扩展标签参数。
        """
        return ViewParam(
            function_name=info.tab_name,
            title=info.tab_name,
            html="UI/index.html",
            css=tuple(info.css_files),
            js=tuple(info.js_files),
            feature_cls=info.feature_cls,
            description=info.description or "第三方扩展",
            base_url="/extensions/%s/" % urllib.parse.quote(info.id),
            resource_root=str(info.path),
        )

    def _register_settings_group(self, name: str, tag: TagView) -> None:
        """把一个标签的设置组绑定启用开关并注册到设置页。

        Args:
            name: 标签名。
            tag: 标签页实例。
        """
        settings_tag: TagView | None = self._tags.get(SETTINGS_NAME)
        if settings_tag is None:
            return
        try:
            group = tag.settings_group
        except Exception:  # 第三方扩展的设置组异常不应拖垮设置页。
            _LOGGER.exception("读取设置组失败: %s", name)
            return
        if not group.enabled_editable:
            group.bind_enabled(
                lambda: self._is_feature_enabled(name),
                lambda enabled: self._set_feature_enabled(name, enabled),
                editable=True,
            )
        if group.field_specs or group.enabled_editable:
            settings_tag.register_settings_field(group)

    def _set_feature_enabled(self, name: str, enabled: bool) -> None:
        """设置功能启用状态并刷新标签顺序。

        Args:
            name: 功能标签名。
            enabled: 是否启用。
        """
        extension_api.set_feature_enabled(name, enabled)
        self._temporary_extensions.discard(name)
        self._refresh_order()

    def _register_about_metas(self) -> None:
        """把所有功能的元信息注册到“关于”页。"""
        about_tag: TagView | None = self._tags.get(ABOUT_NAME)
        if about_tag is None:
            return
        register: Any = getattr(about_tag.feature, "register_meta", None)
        if not callable(register):
            return
        for name, tag in self._tags.items():
            if name in (SETTINGS_NAME, ABOUT_NAME):
                continue
            try:
                register(tag.feature.about_meta)
            except Exception:  # 第三方扩展缺少元信息时不影响其它功能。
                _LOGGER.exception("注册关于元信息失败: %s", name)

    def register_extension_dir(
        self,
        path: str,
        temporary: bool = False,
    ) -> dict[str, Any]:
        """在运行期加载一个扩展目录并注册为标签。

        Args:
            path: 扩展目录。
            temporary: 是否为“测试插件”临时加载（不写入启用配置）。

        Returns:
            含 ``tab`` 与 ``extension`` 的字典。

        Raises:
            RuntimeError: 扩展非法或与现有功能重名时抛出。
        """
        info = extension_api.load_extension_dir(Path(path))
        if info.tab_name in (SETTINGS_NAME, ABOUT_NAME):
            raise RuntimeError("扩展标签名不能使用保留名称")
        existing: TagView | None = self._tags.get(info.tab_name)
        if existing is not None:
            # 只允许覆盖已有扩展（调试热替换），绝不覆盖官方功能。
            if info.tab_name not in self._extension_names:
                raise RuntimeError("标签名已存在：%s" % info.tab_name)
            settings_tag: TagView | None = self._tags.get(SETTINGS_NAME)
            remove = getattr(settings_tag.feature, "unregister_group", None) if settings_tag else None
            if callable(remove):
                remove(existing.settings_group.group_id)
            self._tags.pop(info.tab_name, None)
            unregister_extension_param(info.tab_name)
        self._extension_names.add(info.tab_name)
        self._extension_dirs[info.id] = info.path
        register_extension_param(self._extension_view_param(info))
        tag: TagView = TagView.load(info.tab_name, self._universal_param)
        self._tags[info.tab_name] = tag
        if temporary:
            self._temporary_extensions.add(info.tab_name)
        else:
            self._temporary_extensions.discard(info.tab_name)
        self._register_settings_group(info.tab_name, tag)
        about_tag: TagView | None = self._tags.get(ABOUT_NAME)
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
        self._refresh_order()
        return {"tab": info.tab_name, "extension": info.payload(True)}

    def _current_window(self) -> webview.Window | None:
        """返回当前 pywebview 窗口。

        Returns:
            窗口对象；尚未创建时返回 ``None``。
        """
        if self._window is not None:
            return self._window
        return webview.windows[0] if webview.windows else None

    def _pick_directory(self, title: str, initial: str = "") -> str:
        """弹出原生目录选择框。

        Args:
            title: 对话框标题（pywebview 当前不展示，但保留语义）。
            initial: 初始目录。

        Returns:
            选中的目录；取消时为空字符串。
        """
        window: webview.Window | None = self._current_window()
        if window is None:
            return ""
        try:
            result: Any = window.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=initial or "",
                allow_multiple=False,
            )
        except Exception:
            _LOGGER.exception("目录选择失败: %s", title)
            return ""
        if not result:
            return ""
        return str(result[0] if isinstance(result, (list, tuple)) else result)

    def _pick_file(
        self,
        title: str,
        initial: str = "",
        file_types: tuple[str, ...] = (),
    ) -> str:
        """弹出原生文件选择框。

        Args:
            title: 对话框标题。
            initial: 初始目录。
            file_types: 允许的文件类型。

        Returns:
            选中的文件；取消时为空字符串。
        """
        window: webview.Window | None = self._current_window()
        if window is None:
            return ""
        try:
            result: Any = window.create_file_dialog(
                webview.OPEN_DIALOG,
                directory=initial or "",
                allow_multiple=False,
                file_types=file_types,
            )
        except Exception:
            _LOGGER.exception("文件选择失败: %s", title)
            return ""
        if not result:
            return ""
        return str(result[0] if isinstance(result, (list, tuple)) else result)

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
        """返回供前端渲染的标签列表（含必要设置状态）。

        Returns:
            按最终顺序排列的标签描述。
        """
        self._refresh_order()
        payload: list[dict[str, Any]] = []
        for name in self._order:
            tag: TagView = self._tags[name]
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
            return failure("调用失败: %s" % exc, code=ErrorCode.INTERNAL.value)

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
            extension_resolver=self._resolve_extension_dir,
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
            # 导出构建若带自定义图标，pywebview 会用它设置窗口/任务栏图标；
            # 没有自定义图标时，Windows 后端会自动从 exe 资源中提取。
            webview.start(
                debug=bool(self._ui_config.get("debug", False)),
                icon=APP_ICON or None,
            )
        finally:
            self._window = None
            self.stop_server()
