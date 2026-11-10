# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-10 13:00
# 文件名: discussion.py
# 主要用途: 讨论任务：复制上一条回复（无回复时使用默认文本）、填写编辑器与匿名发布。
# 文件版本: 4.4.0
"""讨论任务：复制上一条回复，匿名发布。

- 讨论单元的 contentId 就是讨论详情页的 ``pid``。
- 默认 dry-run，只有 ``submit=True`` 才点击「发表回复」。
- 2026-11 页面同时存在旧版 ``.j-reply-all`` 与新版 ``article.soft-shell`` 结构；
  这里同时兼容，并在讨论详情页不可用时回退到内容页。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import Course, Task
from ..pages import learn_url
from ..pages.discussion_page import DiscussionPage
from .base import (
    ActionContext,
    ActionUnavailable,
    SILENT_DISCUSSION_WARNING,
    safe_screenshot,
)

DISCUSSION_KIND = "讨论"
DEFAULT_REPLY_TEXT = "已学习本节内容，感谢老师讲解。"


def last_non_empty(values: list[str]) -> str:
    """返回列表中最后一个非空字符串。

    Args:
        values: 候选文本。

    Returns:
        最后一个非空文本；全空时返回空字符串。
    """
    for value in reversed(values):
        text: str = str(value or "").strip()
        if text:
            return text
    return ""


@dataclass
class DiscussionResult:
    task: Task
    url: str
    copied_text: str
    filled: bool = False
    anonymous: bool = False
    submitted: bool = False
    fallback_reply: bool = False
    message: str = ""
    screenshot: str = ""


class DiscussionAction:
    def __init__(self, ctx: ActionContext) -> None:
        self.ctx = ctx

    def run(
        self,
        course: Course,
        task: Task,
        *,
        submit: bool = False,
        silent: bool = False,
    ) -> DiscussionResult:
        self.ctx.check_cancel()
        if not course.school_short_name or not course.course_id:
            raise ActionUnavailable("课程缺少 schoolShortName/courseId")
        if not task.content_id:
            raise ActionUnavailable(f"任务「{task.name}」没有讨论 pid（contentId）")
        if silent:
            self.ctx.require_silent_consent(SILENT_DISCUSSION_WARNING)

        base: str = learn_url(
            course.school_short_name,
            course.course_id,
            course.term_id,
            spoc=course.is_spoc,
        )
        page, surface = self._open_target(course, task, base)

        copied: str = self._last_reply_text(surface)
        fallback_reply: bool = False
        if not copied:
            copied = DEFAULT_REPLY_TEXT
            fallback_reply = True
            self.ctx.warn("未找到可复制的回复，使用默认回复文本。")
        self.ctx.log(f"已复制上一条回复：{copied[:80]}…")

        self._open_editor(surface)
        filled: bool = self._fill_editor(surface, copied)
        anonymous: bool = self._check_anonymous(surface)

        result = DiscussionResult(
            task=task,
            url=str(getattr(page, "url", "") or ""),
            copied_text=copied,
            filled=filled,
            anonymous=anonymous,
            fallback_reply=fallback_reply,
        )
        result.screenshot = safe_screenshot(
            self.ctx, page, f".artifacts/discussion-{task.content_id}-dryrun.png"
        )

        if not submit:
            result.message = (
                "已填写（使用默认回复文本），未发布"
                if fallback_reply
                else "已填写，未发布"
            )
            self.ctx.info("已填入回复/勾选匿名，未发表。可在设置中开启自动发布讨论。")
            return result

        self.ctx.info("正在发表回复并等待服务端确认…")
        result.submitted = self._submit(surface)
        if result.submitted:
            result.message = (
                "已发布（使用默认回复文本）" if fallback_reply else "已发布"
            )
            self.ctx.info("讨论回复已发布。")
        else:
            result.message = "已点击发表，但未检测到发表成功"
            self.ctx.warn(
                "已点击「发表回复」，但 15 秒内未检测到发表成功；"
                "请打开页面确认，任务状态可能尚未更新。"
            )
        suffix = "submitted" if result.submitted else "submit-unconfirmed"
        result.screenshot = safe_screenshot(
            self.ctx, page, f".artifacts/discussion-{task.content_id}-{suffix}.png"
        )
        return result

    # ------------------------------------------------------------------ 页面
    def _open_target(self, course: Course, task: Task, base: str) -> tuple[Any, Any]:
        return DiscussionPage(self.ctx)._open_target(course, task, base)

    def _find_surface(self, page: Any) -> Any:
        return DiscussionPage(self.ctx, page)._find_surface(page)

    def _wait_ready(self, page: Any, *, timeout_ms: int = 45000) -> Any:
        return DiscussionPage(self.ctx, page)._wait_ready(page, timeout_ms=timeout_ms)

    def _dismiss(self, page: Any) -> None:
        DiscussionPage(self.ctx, page)._dismiss(page)

    def _last_reply_text(self, surface: Any) -> str:
        return DiscussionPage(self.ctx)._last_reply_text(surface)

    def _open_editor(self, surface: Any) -> None:
        DiscussionPage(self.ctx)._open_editor(surface)

    def _fill_editor(self, surface: Any, text: str) -> bool:
        return DiscussionPage(self.ctx)._fill_editor(surface, text)

    def _check_anonymous(self, surface: Any) -> bool:
        return DiscussionPage(self.ctx)._check_anonymous(surface)

    def _submit(self, surface: Any) -> bool:
        return DiscussionPage(self.ctx)._submit(surface)
