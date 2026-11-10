# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-10 13:00
# 文件名: base.py
# 主要用途: Page Object 基类与页面运行时：统一截图、等待、取消检查与日志。
# 文件版本: 4.4.0
"""icourse Page Object 基类。"""
from __future__ import annotations

from typing import Any

from ..actions.base import ActionContext, safe_screenshot

__version__ = "4.4.0"
__author__ = "Gary"
__all__ = ["PageObject"]


class PageObject:
    """一个页面对象的公共运行时。"""

    def __init__(self, ctx: ActionContext, page: Any | None = None) -> None:
        """初始化页面对象。

        Args:
            ctx: 动作上下文（提供日志、取消、浏览器会话）。
            page: 已获取的 Playwright Page；空时由子类打开。
        """
        self.ctx: ActionContext = ctx
        self.page: Any | None = page

    def check_cancel(self) -> None:
        """检查协作取消。"""
        self.ctx.check_cancel()

    def wait(self, milliseconds: int) -> None:
        """等待页面毫秒数。"""
        assert self.page is not None
        self.page.wait_for_timeout(milliseconds)

    def screenshot(self, name: str) -> str:
        """安全截图。"""
        assert self.page is not None
        return safe_screenshot(self.ctx, self.page, name)

    def info(self, message: str) -> None:
        """输出信息日志。"""
        self.ctx.info(message)

    def warn(self, message: str) -> None:
        """输出警告日志。"""
        self.ctx.warn(message)
