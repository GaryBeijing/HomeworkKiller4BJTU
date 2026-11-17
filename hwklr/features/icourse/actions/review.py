# -*- coding: utf-8 -*-
# 作者: Gary (Adapted from GinsMooc by gin)
# 编写日期: 2026-11-17 10:00
# 最后更新: 2026-11-17 10:00
# 文件名: review.py
# 主要用途: 实验性自动互评：打开作业互评页、选择满分、随机填写评语并逐份提交。
# 文件版本: 4.7.0
"""实验性自动互评动作。

互评流程参考 GinsMooc 扩展（©2022-2024 gin），归属说明见项目根目录 NOTICE。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..models import Course, Task
from ..pages import close_modals, learn_url, new_assessment_url, new_testlist_url, open_route
from ..pages.review_page import ReviewPage
from ..review_comments import CommentPicker
from .base import ActionCancelled, ActionContext, ActionUnavailable, safe_screenshot

__version__ = "4.7.0"
__author__ = "Gary (Adapted from GinsMooc by gin)"
__all__ = ["MAX_PEER_REVIEW_LIMIT", "PeerReviewAction", "PeerReviewResult"]

MAX_PEER_REVIEW_LIMIT = 20
_READY_TIMEOUT_MS = 30_000
_SUBMIT_TIMEOUT_MS = 20_000


@dataclass
class PeerReviewResult:
    """一次互评任务的结果。"""

    task: Task
    url: str = ""
    available: bool = False
    attempted: int = 0
    reviewed: int = 0
    comments: list[str] = field(default_factory=list)
    message: str = ""
    screenshot: str = ""


class PeerReviewAction:
    """自动完成作业互评。"""

    def __init__(self, ctx: ActionContext) -> None:
        self.ctx = ctx

    def run(self, course: Course, task: Task) -> PeerReviewResult:
        """执行互评；无待互评时返回 ``available=False``。"""
        result = PeerReviewResult(task=task)
        if course.is_spoc:
            result.message = "互评自动化仅支持 MOOC"
            return result
        if not task.test_id:
            result.message = "该作业没有 id"
            return result
        page = self.ctx.acquire_page()
        try:
            page = self._open_review_page(page, course, task, result)
        except ActionCancelled:
            raise
        except Exception as exc:
            self.ctx.warn("打开互评页失败：%s" % exc)
            result.message = "无法打开互评页"
            return result
        if page is None:
            result.message = result.message or "未检测到待互评作业"
            return result

        review = ReviewPage(self.ctx, page)
        result.url = str(getattr(page, "url", "") or "")
        try:
            picker = CommentPicker()
        except Exception as exc:
            raise ActionUnavailable("互评评语库不可用：%s" % exc) from exc
        last_signature: str = ""
        try:
            for _ in range(MAX_PEER_REVIEW_LIMIT):
                self.ctx.check_cancel()
                state = review.state()
                if state.get("noPending"):
                    result.available = True
                    break
                if not state.get("reviewMode"):
                    if result.attempted == 0:
                        result.message = "未检测到互评题目"
                    break
                result.available = True
                signature = review.signature()
                if signature and signature == last_signature:
                    self.ctx.warn("互评题目未变化，停止以避免重复提交。")
                    break
                last_signature = signature

                result.attempted += 1
                selection = review.select_full_marks()
                groups = int(selection.get("groups") or 0)
                selected = int(selection.get("selected") or 0)
                if groups == 0 or selected < groups:
                    raise ActionUnavailable("未找到完整的互评评分项，未提交。")
                comment = picker.next()
                filled = review.fill_comment(comment)
                if filled <= 0:
                    raise ActionUnavailable("未找到互评评语输入框，未提交。")
                if not review.click_submit():
                    raise ActionUnavailable("未找到互评提交按钮，未提交。")
                if not self._wait_submitted(review, page):
                    self.ctx.warn("已点击提交，但未确认互评成功；停止后续提交。")
                    break
                result.reviewed += 1
                result.comments.append(comment)
                self.ctx.info("已提交第 %d 份互评。" % result.reviewed)
                self.ctx.check_cancel()
                state = review.state()
                if state.get("noPending"):
                    break
                if state.get("nextVisible"):
                    if not review.click_next():
                        break
                    page.wait_for_timeout(1800)
                else:
                    break
        except ActionCancelled:
            raise
        except ActionUnavailable as exc:
            if result.reviewed == 0 and result.attempted <= 1:
                raise
            self.ctx.warn(str(exc))
            result.message = str(exc)
        except Exception as exc:
            if result.reviewed == 0:
                raise ActionUnavailable("互评失败：%s" % exc) from exc
            self.ctx.warn("互评中断：%s" % exc)
            result.message = "互评中断：%s" % exc

        result.url = str(getattr(page, "url", "") or result.url)
        if result.reviewed:
            result.message = "已互评 %d 份" % result.reviewed
        elif result.attempted:
            result.message = "已尝试互评，但未确认提交成功"
        elif not result.message:
            result.message = "未检测到待互评作业"
        if result.reviewed != result.attempted:
            result.screenshot = safe_screenshot(
                self.ctx, page, f".artifacts/peer-review-{task.test_id}-failed.png"
            )
        return result

    # ------------------------------------------------------------------ 打开
    def _open_review_page(
        self, page: Any, course: Course, task: Task, result: PeerReviewResult
    ) -> Any:
        """按新版路由、旧版路由、评估列表依次尝试进入互评。"""
        base = learn_url(
            course.school_short_name,
            course.course_id,
            course.term_id,
            spoc=course.is_spoc,
        )
        new_url = new_assessment_url(
            course.school_short_name,
            course.course_id,
            course.term_id,
            "作业",
            int(task.test_id or 0),
        )
        try:
            page.goto(new_url, wait_until="domcontentloaded", timeout=90_000)
            close_modals(page)
            page.wait_for_timeout(1800)
            page = self._adopt_new_page(page)
            entered = self._enter_review(page)
            if entered is not None:
                return entered
            page = self._adopt_new_page(page)
            state = ReviewPage(self.ctx, page).state()
            if state.get("noPending"):
                result.available = True
                return page
        except Exception as exc:
            self.ctx.warn("新版作业路由打开失败：%s" % exc)

        try:
            open_route(page, base, f"#/learn/hw?id={int(task.test_id or 0)}")
            close_modals(page)
            page.wait_for_timeout(1500)
            page = self._adopt_new_page(page)
            entered = self._enter_review(page)
            if entered is not None:
                return entered
        except Exception as exc:
            self.ctx.warn("旧版作业路由打开失败：%s" % exc)

        try:
            page.goto(
                new_testlist_url(
                    course.school_short_name, course.course_id, course.term_id
                ),
                wait_until="domcontentloaded",
                timeout=90_000,
            )
            page.wait_for_timeout(1500)
            from .quiz import TESTLIST_CLICK_JS

            clicked = page.evaluate(TESTLIST_CLICK_JS, task.name)
            if clicked:
                page.wait_for_timeout(1800)
                page = self._adopt_new_page(page)
                entered = self._enter_review(page)
                if entered is not None:
                    return entered
        except Exception as exc:
            self.ctx.warn("从评估列表打开作业失败：%s" % exc)
        return None

    def _enter_review(self, page: Any) -> Any | None:
        """点击互评入口并等待互评题目；成功时返回实际页面。"""
        review = ReviewPage(self.ctx, page)
        state = review.state()
        if state.get("reviewMode"):
            return page
        if state.get("noPending"):
            return None
        clicked = review.click_entry()
        if not clicked:
            return None
        self.ctx.info("已点击互评入口：%s" % clicked)
        page = self._adopt_new_page(page)
        review = ReviewPage(self.ctx, page)
        deadline = time.monotonic() + (_READY_TIMEOUT_MS / 1000)
        while time.monotonic() < deadline:
            page.wait_for_timeout(1000)
            state = review.state()
            if state.get("reviewMode"):
                return page
            if state.get("noPending"):
                return None
        return None

    @staticmethod
    def _adopt_new_page(page: Any) -> Any:
        """互评入口若打开新标签页，切换到最新页面。"""
        try:
            pages = list(page.context.pages)
            if pages and pages[-1] is not page:
                return pages[-1]
        except Exception:
            pass
        return page

    def _wait_submitted(self, review: ReviewPage, page: Any) -> bool:
        """等待明确的互评提交成功信号。"""
        deadline = time.monotonic() + (_SUBMIT_TIMEOUT_MS / 1000)
        while time.monotonic() < deadline:
            self.ctx.check_cancel()
            state = review.state()
            if state.get("noPending") or state.get("nextVisible"):
                return True
            if state.get("successText"):
                return True
            page.wait_for_timeout(800)
        return False
