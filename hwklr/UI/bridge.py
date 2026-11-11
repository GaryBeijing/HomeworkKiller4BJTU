# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-10 23:00
# 最后更新: 2026-11-11 10:00
# 文件名: bridge.py
# 主要用途: 暴露给前端的 pywebview JS 桥接对象 BridgeApi（标签路由、更新检查与外部链接）。
# 文件版本: 4.4.3
"""JS 桥接对象。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .window import WindowView

__version__ = "4.4.3"
__author__ = "Gary"
__all__ = ["BridgeApi"]


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
        self._window_view: "WindowView" = window_view

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

    # ---------------------------------------------------------------- 更新
    def check_update(self) -> dict[str, Any]:
        """启动一次版本检查并返回更新状态。"""
        return self._window_view.check_update()

    def get_update_state(self) -> dict[str, Any]:
        """返回当前更新状态快照。"""
        return self._window_view.update_state()

    def start_update_download(self) -> dict[str, Any]:
        """开始下载已发现的更新。"""
        return self._window_view.start_update_download()

    def install_update(self, restart: bool = True) -> dict[str, Any]:
        """记录待安装更新；``restart`` 为真时安装并重启。"""
        return self._window_view.install_update(bool(restart))

    def open_url(self, url: str) -> dict[str, Any]:
        """用系统默认浏览器打开受信任的发布页。"""
        return self._window_view.open_external_url(str(url or ""))
