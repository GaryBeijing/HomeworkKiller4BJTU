# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-10 23:05
# 文件名: extension_runtime.py
# 主要用途: 运行期第三方扩展的扫描、资源参数转换、目录解析与数据库 provider 注册。
# 文件版本: 4.4.1
"""运行期扩展注册。

本模块只负责扩展资产的登记与查找；把扩展加载为标签页实例由
:class:`hwklr.UI.registry.TagRegistry` 与窗口层完成。
"""
from __future__ import annotations

import logging
import urllib.parse
from pathlib import Path
from typing import Any, Final

from hwklr import db
from hwklr.features import extensions as extension_api

from .tagview.view_data import (
    ViewParam,
    all_view_params,
    register_extension_param,
    unregister_extension_param,
)

__version__ = "4.4.1"
__author__ = "Gary"
__all__ = ["ExtensionRuntime"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_DEFAULT_EXTENSION_ORDER: Final[int] = 500


class ExtensionRuntime:
    """管理已安装扩展的标签名、资源目录与临时加载状态。"""

    def __init__(self, db_manager: db.DbManager) -> None:
        """初始化运行期扩展注册表。

        Args:
            db_manager: 用于注册插件声明的数据库 provider。
        """
        self._db_manager: db.DbManager = db_manager
        self.names: set[str] = set()
        self.dirs: dict[str, Path] = {}
        self.errors: list[str] = []
        self.temporary: set[str] = set()

    def load_installed(self) -> list[Any]:
        """扫描 ``extension/`` 并登记可用扩展参数。

        Returns:
            已加载的 :class:`ExtensionInfo` 列表。
        """
        infos, errors = extension_api.scan_installed_extensions()
        self.errors = list(errors)
        loaded: list[Any] = []
        for info in infos:
            if (
                info.tab_name in all_view_params()
                or info.tab_name in self.names
            ):
                self.errors.append(
                    "%s：扩展标签名与现有功能重复" % info.tab_name
                )
                continue
            self.adopt(info)
            loaded.append(info)
        return loaded

    def adopt(self, info: Any, temporary: bool = False) -> None:
        """登记扩展参数、资源目录与数据库 provider。

        Args:
            info: :class:`hwklr.features.extensions.ExtensionInfo`。
            temporary: 是否为“测试插件”临时加载。
        """
        self.names.add(info.tab_name)
        self.dirs[info.id] = info.path
        if temporary:
            self.temporary.add(info.tab_name)
        else:
            self.temporary.discard(info.tab_name)
        register_extension_param(self.view_param(info))
        self._register_database(info)

    def failed(self, name: str) -> None:
        """撤销一个加载失败的扩展标签。

        Args:
            name: 标签名。
        """
        self.names.discard(name)
        self.temporary.discard(name)
        unregister_extension_param(name)
        self.errors.append("%s：标签加载失败" % name)

    def is_temporary(self, name: str) -> bool:
        """返回是否为本次运行临时加载的扩展。

        Args:
            name: 标签名。

        Returns:
            临时扩展返回 ``True``。
        """
        return str(name or "") in self.temporary

    def resolve_dir(self, extension_id: str) -> Path | None:
        """按扩展 ID 返回前端资源根目录。

        Args:
            extension_id: 扩展目录名（已 URL 解码）。

        Returns:
            扩展根目录；未注册时返回 ``None``。
        """
        return self.dirs.get(str(extension_id or ""))

    @staticmethod
    def view_param(info: Any) -> ViewParam:
        """把扩展信息转换为标签参数。

        Args:
            info: :class:`hwklr.features.extensions.ExtensionInfo`。

        Returns:
            扩展标签参数。
        """
        assets: Any = getattr(info, "assets", None)
        html: str = (
            assets.html if assets is not None and assets.html else "UI/index.html"
        )
        css: tuple[str, ...] = (
            tuple(assets.css) if assets is not None and assets.css
            else tuple(info.css_files)
        )
        js: tuple[str, ...] = (
            tuple(assets.js) if assets is not None and assets.js
            else tuple(info.js_files)
        )
        return ViewParam(
            function_name=info.tab_name,
            title=info.tab_name,
            html=html,
            css=css,
            js=js,
            feature_cls=info.feature_cls,
            description=info.description or "第三方扩展",
            base_url="/extensions/%s/" % urllib.parse.quote(info.id),
            resource_root=str(info.path),
            order=int(getattr(info, "order", 0) or _DEFAULT_EXTENSION_ORDER),
            actions=tuple(getattr(info, "actions", ()) or ()),
        )

    def _register_database(self, info: Any) -> None:
        """注册插件 manifest 声明的数据库 provider。

        Args:
            info: 扩展信息。
        """
        provider: Any = getattr(info, "db_provider", None)
        if provider is None:
            return
        try:
            self._db_manager.register(provider)
        except (TypeError, ValueError) as exc:
            name: str = str(getattr(provider, "base_name", "unknown"))
            self.errors.append(
                "%s：数据库 provider 注册失败（%s）" % (name, exc)
            )
            _LOGGER.warning("扩展数据库注册失败 %s: %s", info.tab_name, exc)
