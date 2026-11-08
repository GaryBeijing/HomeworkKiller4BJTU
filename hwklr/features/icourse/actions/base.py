# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: base.py
# 主要用途: 动作层公共上下文：日志回调、取消检查与页面获取；已移除终端确认与 rich 输出。
# 文件版本: 4.0.0
"""动作层公共设施。"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from ..browser_session import BrowserSession

SILENT_VIDEO_WARNING = (
    "您即将在后台静默启动课程，您可能会错过一些重要内容，三思而后行"
)
SILENT_DISCUSSION_WARNING = (
    "您即将在后台静默完成讨论，您可能会错过一些重要内容，三思而后行"
)
SILENT_DOCUMENT_WARNING = (
    "您即将在后台下载文档并把该文档标记为已完成，三思而后行"
)

LogCallback = Callable[[str, str], None]


class ActionCancelled(Exception):
    """任务被用户取消或无法继续。"""


@dataclass
class ActionContext:
    """一次动作执行所需的上下文。"""

    session: BrowserSession
    repository: Any | None = None
    page: Any | None = None
    interactive: bool = False
    log_callback: LogCallback | None = None
    cancel_event: threading.Event | None = field(default_factory=threading.Event)

    def acquire_page(self) -> Any:
        """返回该 worker 独占的 Page。

        Returns:
            Playwright Page。
        """
        if self.page is not None:
            return self.page
        return self.session.page("icourse163") or self.session.new_page()

    def log(self, message: str) -> None:
        """输出调试日志。"""
        self._emit("log", message)

    def info(self, message: str) -> None:
        """输出普通进度信息。"""
        self._emit("info", message)

    def warn(self, message: str) -> None:
        """输出警告信息。"""
        self._emit("warn", message)

    def _emit(self, level: str, message: str) -> None:
        """调用日志回调。

        Args:
            level: 日志级别。
            message: 文本。
        """
        callback = self.log_callback
        if callback is None:
            return
        try:
            callback(level, str(message))
        except Exception:
            pass

    def cancelled(self) -> bool:
        """返回是否已请求取消。

        Returns:
            已取消返回 ``True``。
        """
        return bool(self.cancel_event and self.cancel_event.is_set())

    def check_cancel(self) -> None:
        """若已请求取消则抛出 :class:`ActionCancelled`。

        Raises:
            ActionCancelled: 已请求取消。
        """
        if self.cancelled():
            raise ActionCancelled("任务已取消。")

    def require_silent_consent(self, warning: str) -> None:
        """GUI 已在“开始完成”弹窗中确认；这里仅记录警告。

        Args:
            warning: 警告文本。
        """
        self.check_cancel()
        self.warn(warning)

    def wait_ok(self, prompt: str = "") -> bool:
        """GUI 中不等待终端确认。

        Args:
            prompt: 忽略。

        Returns:
            始终为 ``True``。
        """
        return True
