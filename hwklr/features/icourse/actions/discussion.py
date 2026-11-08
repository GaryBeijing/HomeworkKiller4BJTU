# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: discussion.py
# 主要用途: 讨论任务：复制上一条回复、填写编辑器与匿名发布。
# 文件版本: 4.0.0
"""讨论任务：复制上一条回复，匿名发布。

- 讨论单元的 contentId 就是讨论详情页的 ``pid``。
- 默认 dry-run，只有 ``submit=True`` 才点击「发表回复」。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..models import Course, Task
from ..pages import close_modals, learn_url, open_route, page_block_reason
from .base import ActionCancelled, ActionContext, SILENT_DISCUSSION_WARNING

DISCUSSION_KIND = "讨论"
SUBMIT_CONFIRM_TIMEOUT_MS = 10_000
SUBMIT_POLL_MS = 500


@dataclass
class DiscussionResult:
    task: Task
    url: str
    copied_text: str
    filled: bool = False
    anonymous: bool = False
    submitted: bool = False
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
            raise ActionCancelled("课程缺少 schoolShortName/courseId")
        if not task.content_id:
            raise ActionCancelled(f"任务「{task.name}」没有讨论 pid（contentId）")
        if silent:
            self.ctx.require_silent_consent(SILENT_DISCUSSION_WARNING)

        base = learn_url(
            course.school_short_name,
            course.course_id,
            course.term_id,
            spoc=course.is_spoc,
        )
        hash_path = f"#/learn/forumdetail?pid={int(task.content_id)}"
        url = base + hash_path
        page = self.ctx.acquire_page()
        open_route(page, base, hash_path)
        self._dismiss(page)
        blocked = page_block_reason(page)
        if blocked:
            self.ctx.session.screenshot(
                page, f".artifacts/discussion-blocked-{task.content_id}.png"
            )
            raise ActionCancelled(f"讨论页无法访问：{blocked}。当前 URL：{page.url}")
        try:
            page.wait_for_selector(".j-reply-all", timeout=25_000)
            page.wait_for_timeout(800)
        except Exception:
            pass

        copied = self._last_reply_text(page)
        if not copied:
            raise ActionCancelled("没有找到上一条回复，无法复制")
        self.ctx.log(f"已复制上一条回复：{copied[:80]}…")

        self._open_editor(page)
        filled = self._fill_editor(page, copied)
        anonymous = self._check_anonymous(page)

        result = DiscussionResult(
            task=task, url=page.url, copied_text=copied,
            filled=filled, anonymous=anonymous,
        )
        result.screenshot = str(
            self.ctx.session.screenshot(
                page, f".artifacts/discussion-{task.content_id}-dryrun.png"
            )
        )

        if not submit:
            self.ctx.info("已填入回复/勾选匿名，未发表。可在设置中开启自动发布讨论。")
            return result

        self.ctx.info("正在发表回复并等待服务端确认…")
        result.submitted = self._submit(page)
        if result.submitted:
            self.ctx.info("讨论回复已发布。")
        else:
            self.ctx.warn(
                "已点击「发表回复」，但 10 秒内未检测到发表成功；"
                "请打开页面确认，任务状态可能尚未更新。"
            )
        suffix = "submitted" if result.submitted else "submit-unconfirmed"
        result.screenshot = str(
            self.ctx.session.screenshot(
                page, f".artifacts/discussion-{task.content_id}-{suffix}.png"
            )
        )
        return result

    # ------------------------------------------------------------------ 页面
    def _dismiss(self, page) -> None:
        close_modals(page)
        # 并发限制提示会反复弹出；直接移除遮罩，避免挡住点击。
        page.evaluate(
            "() => document.querySelectorAll("
            "'.ux-modal, .ant-modal-root, .m-com-mask'"
            ").forEach(el => el.remove())"
        )
        page.wait_for_timeout(300)

    def _last_reply_text(self, page) -> str:
        return page.evaluate(
            r"""() => {
              const root = document.querySelector('.j-reply-all');
              if (!root) return '';
              const items = [...root.querySelectorAll('.m-detailInfoItem .j-content')];
              for (let i = items.length - 1; i >= 0; i--) {
                const text = (items[i].innerText || '').trim();
                if (text) return text;
              }
              return '';
            }"""
        ) or ""

    def _open_editor(self, page) -> None:
        button = page.locator("a.j-replyBtn")
        if button.count() == 0:
            raise ActionCancelled("没有找到「回复」按钮")
        try:
            button.first.click(timeout=5000)
        except Exception:
            self._dismiss(page)
            button.first.click(timeout=5000)
        page.wait_for_timeout(800)
        self._dismiss(page)
        try:
            page.wait_for_selector(".ql-editor", timeout=5000)
        except Exception:
            pass

    def _fill_editor(self, page, text: str) -> bool:
        editor = page.locator(".ql-editor")
        for _ in range(10):
            if editor.count() > 0:
                break
            page.wait_for_timeout(500)
        if editor.count() == 0:
            raise ActionCancelled("没有找到回复编辑器（.ql-editor）")
        editor.first.fill(text)
        page.wait_for_timeout(300)
        return True

    def _check_anonymous(self, page) -> bool:
        box = page.locator("input.j-anonycheck")
        if box.count() == 0:
            self.ctx.warn("没有找到匿名勾选框，将按页面默认方式发表。")
            return False
        try:
            box.first.evaluate("el => { if (!el.checked) el.click(); }")
            return bool(box.first.is_checked())
        except Exception:
            try:
                box.first.check()
                return bool(box.first.is_checked())
            except Exception:
                return False

    def _reply_count(self, page) -> int:
        try:
            return int(
                page.evaluate(
                    """() => document.querySelectorAll(
                      '.j-reply-all .m-detailInfoItem'
                    ).length"""
                )
                or 0
            )
        except Exception:
            return 0

    @staticmethod
    def _success_toast(page) -> bool:
        try:
            return bool(
                page.evaluate(
                    """() => {
                      const hits = ['发表成功', '发布成功', '回复成功',
                                    '提交成功', '操作成功'];
                      const nodes = [...document.querySelectorAll(
                        '.ux-toast, .ant-message, .u-tip, [class*=toast], [class*=Toast]'
                      )].filter(el => {
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                      });
                      const text = nodes.map(el => el.innerText || '').join(' ');
                      return hits.some(hit => text.includes(hit));
                    }"""
                )
            )
        except Exception:
            return False

    def _wait_submitted(self, page, before: int) -> bool:
        """点击后等待明确的成功信号，而不是仅凭点击就认为已提交。"""
        deadline = time.monotonic() + SUBMIT_CONFIRM_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            self.ctx.check_cancel()
            if self._success_toast(page):
                return True
            if self._reply_count(page) > before:
                return True
            page.wait_for_timeout(SUBMIT_POLL_MS)
        return False

    def _submit(self, page) -> bool:
        button = page.locator("a.j-edit-btn")
        if button.count() == 0:
            raise ActionCancelled("没有找到「发表回复」按钮")
        before = self._reply_count(page)
        try:
            button.first.click(timeout=5000)
        except Exception:
            self._dismiss(page)
            button.first.click(timeout=5000)
        page.wait_for_timeout(800)
        confirmed = self._wait_submitted(page, before)
        close_modals(page)
        return confirmed
