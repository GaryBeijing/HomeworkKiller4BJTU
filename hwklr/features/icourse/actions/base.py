# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-11 10:00
# 文件名: base.py
# 主要用途: 动作层公共上下文：日志回调、取消检查、页面获取与安全截图（受留存数据开关控制）。
# 文件版本: 4.4.3
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
    """任务被用户主动取消。"""


class ActionUnavailable(Exception):
    """任务无法继续（页面结构、登录或缺少数据），不是用户主动取消。"""


@dataclass(frozen=True)
class BrowserContext:
    """浏览器会话与页面。"""

    session: BrowserSession
    page: Any | None = None


@dataclass(frozen=True)
class RunContext:
    """日志、交互与取消控制。"""

    interactive: bool = False
    log_callback: LogCallback | None = None
    cancel_event: threading.Event | None = None


@dataclass(frozen=True)
class RepositoryContext:
    """题库/答案仓储。"""

    repository: Any | None = None


@dataclass
class ActionContext:
    """一次动作执行所需的上下文。

    首版保留原有字段；新代码可继续使用 ``ctx``，也可通过 ``browser/run/
    repository_context`` 取得更窄的上下文。
    """

    session: BrowserSession
    repository: Any | None = None
    page: Any | None = None
    interactive: bool = False
    log_callback: LogCallback | None = None
    cancel_event: threading.Event | None = field(default_factory=threading.Event)
    # 关闭“留存数据”后不再写任何任务截图；已有文件不删除。
    retain_data: bool = True

    @property
    def browser(self) -> BrowserContext:
        """返回浏览器上下文视图。"""
        return BrowserContext(self.session, self.page)

    @property
    def run(self) -> RunContext:
        """返回运行控制视图。"""
        return RunContext(self.interactive, self.log_callback, self.cancel_event)

    @property
    def repository_context(self) -> RepositoryContext:
        """返回仓储视图。"""
        return RepositoryContext(self.repository)

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


def safe_screenshot(ctx: ActionContext, page: Any, name: str) -> str:
    """截取诊断截图；截图失败不应把任务本身判为失败。

    Args:
        ctx: 动作上下文。
        page: Playwright Page 或等价页面对象。
        name: 截图文件名（相对 ``artifacts/icourse/``）。

    Returns:
        截图路径；关闭留存或失败时返回空字符串。
    """
    if not bool(getattr(ctx, "retain_data", True)):
        return ""
    try:
        return str(ctx.session.screenshot(page, name))
    except Exception as exc:
        ctx.warn("截图失败：%s" % exc)
        return ""
