# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-10 23:15
# 最后更新: 2026-11-12 13:00
# 文件名: window.py
# 主要用途: pywebview 核心窗口 WindowView：组合标签注册表、扩展运行时、本地 HTTP 服务、欢迎弹窗、跨平台更新服务与窗口生命周期。
# 文件版本: 4.6.1
"""核心窗口。"""
from __future__ import annotations

import json
import logging
import urllib.parse
import webbrowser
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
from hwklr.updater import UpdateService
from hwklr.welcome import mark_welcome_seen, welcome_payload

from .bridge import BridgeApi
from .extension_runtime import ExtensionRuntime
from .registry import TagRegistry
from .server import UiHttpServer
from .tagview import TagView

__version__ = "4.6.1"
__author__ = "Gary"
__all__ = ["WindowView"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_UI_DIR: Final[Path] = Path(__file__).resolve().parent
_PAGE_DATA_DIR: Final[Path] = _UI_DIR / "page_data"
_VIEW_DATA_DIR: Final[Path] = _UI_DIR / "tagview" / "view_data"
_WINDOW_BACKGROUND: Final[str] = "#2f3ab2"


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
        self._active_name: str | None = None
        self._server: UiHttpServer | None = None
        self._window: webview.Window | None = None
        self._shutdown_done: bool = False
        # 数据库：只实例化并注册 provider，不创建目录，失败也不阻止启动。
        try:
            self._db_manager: db.DbManager = db.init_db_manager()
        except Exception:
            _LOGGER.exception("数据库管理器初始化失败，继续启动")
            self._db_manager = db.get_db_manager()
        self._extensions: ExtensionRuntime = ExtensionRuntime(self._db_manager)
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
        self._registry: TagRegistry = TagRegistry(
            self._universal_param,
            self._extensions,
            self._is_feature_enabled,
            self._set_feature_enabled,
        )
        # 更新服务不注册为标签；前端通过 BridgeApi 查询/下载/安装。
        self._update_service: UpdateService = UpdateService(self.request_exit)

        # 步骤 0：扫描 extension/ 并把可用扩展登记为运行期标签参数。
        self._extensions.load_installed()
        # 步骤 1~4：创建标签、强制顺序、注册设置组与关于元信息。
        self._registry.load_initial()
        self._meta["features"] = self._registry.features_meta

    @property
    def _tags(self) -> dict[str, TagView]:
        """兼容旧代码：返回窗口注册的标签映射副本。"""
        return self._registry.tag_map()

    @property
    def _extension_names(self) -> set[str]:
        """兼容旧代码：返回已加载扩展标签名集合。"""
        return self._extensions.names

    @property
    def _extension_dirs(self) -> dict[str, Path]:
        """兼容旧代码：返回扩展 id 到资源目录的映射。"""
        return self._extensions.dirs

    @property
    def _extension_errors(self) -> list[str]:
        """兼容旧代码：返回扩展加载错误。"""
        return self._extensions.errors

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
        """
        order: list[str] = self._registry.refresh_order()
        self._meta["features"] = self._registry.features_meta
        return order

    def _is_feature_enabled(self, name: str) -> bool:
        """判断功能当前是否应显示在标签栏。

        Args:
            name: 功能标签名。

        Returns:
            启用返回 ``True``；本次运行临时加载的扩展恒为启用。
        """
        if self._extensions.is_temporary(name):
            return True
        return extension_api.is_feature_enabled(name)

    def _set_feature_enabled(self, name: str, enabled: bool) -> None:
        """设置功能启用状态并刷新标签顺序。

        Args:
            name: 功能标签名。
            enabled: 是否启用。
        """
        extension_api.set_feature_enabled(name, enabled)
        self._extensions.temporary.discard(name)
        self._refresh_order()

    def _resolve_extension_dir(self, extension_id: str) -> Path | None:
        """按扩展 ID 返回前端资源根目录。

        Args:
            extension_id: 扩展目录名（已 URL 解码）。

        Returns:
            扩展根目录；未注册时返回 ``None``。
        """
        return self._extensions.resolve_dir(extension_id)

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
        self._registry.install_runtime(info, temporary=temporary)
        self._meta["features"] = self._registry.features_meta
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
        return self._registry.order_names()

    @property
    def tags(self) -> dict[str, TagView]:
        """返回标签映射副本。

        Returns:
            名称到 :class:`TagView` 的字典。
        """
        return self._registry.tag_map()

    @property
    def active_tag(self) -> TagView | None:
        """返回当前激活的标签。

        Returns:
            当前标签；未激活时为 ``None``。
        """
        if self._active_name is None:
            return None
        return self._registry.tag_map().get(self._active_name)

    def tags_payload(self) -> list[dict[str, Any]]:
        """返回供前端渲染的标签列表（含必要设置状态）。

        Returns:
            按最终顺序排列的标签描述。
        """
        return self._registry.payload()

    def meta_payload(self) -> dict[str, Any]:
        """返回供前端读取的应用元信息。

        Returns:
            元信息字典，包含实际监听端口。
        """
        meta: dict[str, Any] = dict(self._meta)
        meta["features"] = self._registry.features_meta
        meta["port"] = int(self._context.get("port", 0))
        return meta

    # ---------------------------------------------------------------- 更新
    def check_update(self) -> dict[str, Any]:
        """启动后台版本检查并返回当前状态。"""
        return self._update_service.check()

    def update_state(self) -> dict[str, Any]:
        """返回更新状态快照。"""
        return self._update_service.snapshot()

    def start_update_download(self) -> dict[str, Any]:
        """开始下载更新资产并返回当前状态。"""
        return self._update_service.download()

    def install_update(self, restart: bool = True) -> dict[str, Any]:
        """写入待安装标记；``restart`` 为真时替换并重启。"""
        return self._update_service.install(restart=restart)

    def request_exit(self) -> None:
        """关闭 pywebview 窗口，让更新脚本可以替换程序。"""
        window: webview.Window | None = self._current_window()
        if window is None:
            return
        try:
            window.destroy()
        except Exception:
            _LOGGER.exception("关闭窗口失败")

    # ------------------------------------------------------------ 欢迎弹窗
    def welcome_payload(self) -> dict[str, Any]:
        """返回欢迎弹窗数据。

        Returns:
            是否展示、版本、协议文本与更新分组。
        """
        return welcome_payload()

    def dismiss_welcome(self, version: str = "") -> dict[str, Any]:
        """记录用户已确认当前版本的欢迎弹窗。

        Args:
            version: 前端回传的版本号。

        Returns:
            ``{"ok": bool}``。
        """
        return {"ok": mark_welcome_seen(str(version or ""))}

    def open_external_url(self, url: str) -> dict[str, Any]:
        """用系统默认浏览器打开受信任的发布页。

        Args:
            url: 目标地址。

        Returns:
            ``{"ok": bool, "error": str}``。
        """
        text: str = str(url or "").strip()
        parsed: urllib.parse.ParseResult = urllib.parse.urlparse(text)
        # 同时校验主机与仓库路径，避免 userinfo/子路径伪装成受信任地址。
        allowed: bool = (
            parsed.scheme == "https"
            and (parsed.hostname or "").lower() in {"github.com", "gitcode.com"}
            and any(
                parsed.path.startswith(prefix)
                for prefix in (
                    "/GaryBeijing/HomeworkKiller4BJTU",
                    "/weixin_68744568/HomeworkKiller4BJTU",
                )
            )
        )
        if not allowed:
            return {"ok": False, "error": "不允许打开该链接"}
        try:
            webbrowser.open(text, new=2)
        except Exception as exc:
            _LOGGER.exception("打开外部链接失败")
            return {"ok": False, "error": "打开链接失败：%s" % exc}
        return {"ok": True, "error": ""}

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
        tagview: TagView | None = self._registry.tag_map().get(tag)
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
            welcome_provider=self.welcome_payload,
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
        canonical: TagView | None = self._registry.tag_map().get(tagview.name)
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
        order: list[str] = self._registry.order_names()
        if not order:
            return
        try:
            self.activate_tagview(self._registry.tag_map()[order[0]])
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
            if not self._shutdown_done:
                self._shutdown_done = True
                self._update_service.shutdown()
                self._registry.shutdown()
            self.stop_server()
