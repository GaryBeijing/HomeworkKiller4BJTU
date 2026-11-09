# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-09 20:40
# 文件名: discussion.py
# 主要用途: 讨论任务：复制上一条回复（无回复时使用默认文本）、填写编辑器与匿名发布。
# 文件版本: 4.3.2
"""讨论任务：复制上一条回复，匿名发布。

- 讨论单元的 contentId 就是讨论详情页的 ``pid``。
- 默认 dry-run，只有 ``submit=True`` 才点击「发表回复」。
- 2026-11 页面同时存在旧版 ``.j-reply-all`` 与新版 ``article.soft-shell`` 结构；
  这里同时兼容，并在讨论详情页不可用时回退到内容页。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..models import Course, Task
from ..pages import close_modals, learn_url, open_route, page_block_reason
from .base import (
    ActionCancelled,
    ActionContext,
    ActionUnavailable,
    SILENT_DISCUSSION_WARNING,
    safe_screenshot,
)

DISCUSSION_KIND = "讨论"
DISCUSSION_READY_TIMEOUT_MS = 45_000
SUBMIT_CONFIRM_TIMEOUT_MS = 15_000
SUBMIT_POLL_MS = 500
DEFAULT_REPLY_TEXT = "已学习本节内容，感谢老师讲解。"

_REPLY_MARKERS = (
    ".j-reply-all, .m-detailInfoItem, .j-content, .ql-editor, "
    "a.j-replyBtn, #forum-reply-form, article.soft-shell"
)


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
    def _open_target(
        self, course: Course, task: Task, base: str
    ) -> tuple[Any, Any]:
        """打开讨论详情页；失败时回退到 discussion 内容页。

        Args:
            course: 当前课程。
            task: 讨论任务。
            base: 学习页基础 URL。

        Returns:
            ``(page, surface)``；surface 可能是 frame。

        Raises:
            ActionUnavailable: 两种页面都无法加载出讨论内容。
        """
        page = self.ctx.acquire_page()
        hash_path: str = f"#/learn/forumdetail?pid={int(task.content_id)}"
        try:
            open_route(page, base, hash_path)
        except ActionCancelled:
            raise
        except Exception as first_error:
            # 导航失败不一定意味着页面不可用；换一个新 Page 再试一次。
            self.ctx.warn(f"讨论详情页首次打开失败：{first_error}")
            try:
                page.close()
            except Exception:
                pass
            self.ctx.check_cancel()
            retry_page = self.ctx.session.new_page()
            self.ctx.page = retry_page
            try:
                open_route(retry_page, base, hash_path)
                page = retry_page
            except ActionCancelled:
                raise
            except Exception as exc:
                safe_screenshot(
                    self.ctx,
                    retry_page,
                    f".artifacts/discussion-{task.content_id}-failed.png",
                )
                raise ActionUnavailable(
                    f"讨论详情页打开失败：{exc}；"
                    f"当前 URL：{getattr(retry_page, 'url', '')}"
                ) from exc

        self._dismiss(page)
        try:
            return page, self._wait_ready(page)
        except ActionUnavailable as first_error:
            if not task.lesson_id or not task.unit_id:
                raise
            self.ctx.warn("讨论详情页未加载出内容，尝试打开讨论内容页…")
            try:
                page.close()
            except Exception:
                pass
            self.ctx.check_cancel()
            fallback_page = self.ctx.session.new_page()
            self.ctx.page = fallback_page
            content_hash: str = (
                f"#/learn/content?type=detail&id={int(task.lesson_id)}"
                f"&cid={int(task.unit_id)}"
            )
            try:
                open_route(fallback_page, base, content_hash)
                self._dismiss(fallback_page)
                return fallback_page, self._wait_ready(
                    fallback_page, timeout_ms=20_000
                )
            except ActionCancelled:
                raise
            except ActionUnavailable:
                raise
            except Exception as exc:
                raise first_error from exc

    def _find_surface(self, page: Any) -> Any:
        """返回包含讨论标记的 Page/Frame；找不到时返回原 Page。"""
        try:
            if page.locator(_REPLY_MARKERS).count() > 0:
                return page
        except Exception:
            pass
        for frame in getattr(page, "frames", [])[1:]:
            try:
                if frame.locator(_REPLY_MARKERS).count() > 0:
                    return frame
            except Exception:
                continue
        return page

    def _wait_ready(self, page: Any, *, timeout_ms: int = DISCUSSION_READY_TIMEOUT_MS) -> Any:
        """等待讨论回复区或编辑器出现。

        Args:
            page: Playwright Page。
            timeout_ms: 最长等待毫秒数。

        Returns:
            包含讨论内容的 Page 或 Frame。

        Raises:
            ActionUnavailable: 超时或页面被重定向/登录墙。
        """
        deadline: float = time.monotonic() + max(0, timeout_ms) / 1000
        started: float = time.monotonic()
        while time.monotonic() < deadline:
            self.ctx.check_cancel()
            surface = self._find_surface(page)
            try:
                if surface.locator(_REPLY_MARKERS).count() > 0:
                    return surface
            except Exception:
                pass
            # 给 SPA 前几秒的登录态渲染留时间，避免过早误判登录墙。
            if time.monotonic() - started >= 5:
                blocked: str = page_block_reason(page)
                if blocked:
                    safe_screenshot(
                        self.ctx, page, ".artifacts/discussion-blocked-wait.png"
                    )
                    raise ActionUnavailable(
                        f"讨论页无法访问：{blocked}。"
                        f"当前 URL：{getattr(page, 'url', '')}"
                    )
            try:
                page.wait_for_timeout(500)
            except Exception as exc:
                raise ActionUnavailable(f"讨论页已关闭：{exc}") from exc
        safe_screenshot(
            self.ctx, page, ".artifacts/discussion-timeout.png"
        )
        raise ActionUnavailable(
            f"讨论页 {int(timeout_ms / 1000)} 秒内未加载出回复或编辑器；"
            f"当前 URL：{getattr(page, 'url', '')}"
        )

    def _dismiss(self, page: Any) -> None:
        try:
            has_editor = page.locator(
                ".ql-editor, [contenteditable='true'], #forum-reply-form"
            ).count() > 0
        except Exception:
            has_editor = False
        # 编辑器已展开时不要再点“关闭/确定”，避免把编辑器一并关掉。
        if not has_editor:
            close_modals(page)
        # 并发限制提示会反复弹出；移除遮罩，但保留包含回复编辑器的容器。
        try:
            page.evaluate(
                "() => document.querySelectorAll("
                "'.ux-modal, .ant-modal-root, .m-com-mask'"
                ").forEach(el => {"
                "  if (el.querySelector('.ql-editor, [contenteditable=\"true\"], "
                "#forum-reply-form')) return;"
                "  el.remove();"
                "})"
            )
        except Exception:
            pass
        page.wait_for_timeout(300)

    def _last_reply_text(self, surface: Any) -> str:
        try:
            values = surface.evaluate(
                r"""() => {
                  const selectors = [
                    '.j-reply-all .m-detailInfoItem .j-content',
                    '.j-reply-all .j-content',
                    '.m-detailInfoItem .j-content',
                    '.f-pr .j-content',
                    'article.soft-shell.p-5 > p',
                    'article.soft-shell p.whitespace-pre-wrap',
                  ];
                  for (const selector of selectors) {
                    const out = [];
                    for (const node of document.querySelectorAll(selector)) {
                      if (node.closest(
                        '#forum-reply-form, .j-reply-add, .ql-editor'
                      )) continue;
                      const text = (node.innerText || '').trim();
                      // 过滤作者/日期行，避免把元数据当成回复正文。
                      if (!text) continue;
                      if (/^\d{4}年\d{1,2}月\d{1,2}日/.test(text)) continue;
                      if (/^\d{1,2}:\d{2}(:\d{2})?$/.test(text)) continue;
                      out.push(text);
                    }
                    // 关键步骤：只使用第一个命中的选择器组，避免退到更宽的
                    // article.soft-shell p 时把作者/日期当成回复正文。
                    if (out.length) return out;
                  }
                  return [];
                }"""
            )
        except Exception:
            return ""
        if not isinstance(values, list):
            return ""
        return last_non_empty([str(value) for value in values])

    def _editor(self, surface: Any) -> Any:
        return surface.locator(
            ".ql-editor, .j-reply-add .ql-editor, "
            "#forum-reply-form .ql-editor, [contenteditable='true']"
        )

    def _open_editor(self, surface: Any) -> None:
        editor = self._editor(surface)
        try:
            if editor.count() > 0 and editor.first.is_visible():
                return
        except Exception:
            pass
        button = surface.locator("a.j-replyBtn")
        if button.count() == 0:
            button = surface.locator('a:has-text("回复"), button:has-text("回复")')
        if button.count() == 0:
            raise ActionUnavailable("没有找到「回复」按钮或已打开的编辑器")
        try:
            button.first.click(timeout=5000)
        except Exception:
            self._dismiss(surface)
            button.first.click(timeout=5000)
        surface.wait_for_timeout(800)
        try:
            surface.wait_for_selector(".ql-editor", timeout=5000)
        except Exception:
            pass

    def _fill_editor(self, surface: Any, text: str) -> bool:
        editor = self._editor(surface)
        for _ in range(20):
            if editor.count() > 0:
                break
            surface.wait_for_timeout(500)
        if editor.count() == 0:
            raise ActionUnavailable("没有找到回复编辑器")
        try:
            editor.first.fill(text)
        except Exception:
            # 富文本编辑器偶尔拦截 fill；退化为直接写 innerText 并触发 input。
            editor.first.evaluate(
                "(el, value) => {"
                "  el.innerText = value;"
                "  el.dispatchEvent(new InputEvent('input', {bubbles: true}));"
                "}",
                text,
            )
        surface.wait_for_timeout(300)
        return True

    def _check_anonymous(self, surface: Any) -> bool:
        box = surface.locator(
            "input.j-anonycheck, label:has-text(\"匿名\") input[type=checkbox]"
        )
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

    def _reply_count(self, surface: Any) -> int:
        try:
            return int(
                surface.evaluate(
                    """() => document.querySelectorAll(
                      '.j-reply-all .m-detailInfoItem, article.soft-shell'
                    ).length"""
                )
                or 0
            )
        except Exception:
            return 0

    @staticmethod
    def _success_toast(surface: Any) -> bool:
        try:
            return bool(
                surface.evaluate(
                    """() => {
                      const hits = ['发表成功', '发布成功', '回复成功',
                                    '回复已发布', '已发布', '提交成功', '操作成功'];
                      const nodes = [...document.querySelectorAll(
                        '.ux-toast, .ant-message, .u-tip, [class*=toast], [class*=Toast]'
                      )].filter(el => {
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                      });
                      const text = nodes.map(el => el.innerText || '').join(' ');
                      if (hits.some(hit => text.includes(hit))) return true;
                      // v2 页面把成功提示直接渲染在回复区，不一定有 toast 类。
                      const bodyText = document.body
                        ? document.body.innerText : '';
                      return bodyText.includes('回复已发布');
                    }"""
                )
            )
        except Exception:
            return False

    def _wait_submitted(self, surface: Any, before: int) -> bool:
        """点击后等待明确的成功信号，而不是仅凭点击就认为已提交。"""
        deadline = time.monotonic() + SUBMIT_CONFIRM_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            self.ctx.check_cancel()
            if self._success_toast(surface):
                return True
            if self._reply_count(surface) > before:
                return True
            surface.wait_for_timeout(SUBMIT_POLL_MS)
        return False

    def _submit(self, surface: Any) -> bool:
        button = surface.locator(
            "a.j-edit-btn, .j-reply-add .editbtn, "
            "#forum-reply-form button[type='submit']"
        )
        try:
            # 优先选择带“发表回复”文字的按钮，避免误点回复项上的编辑按钮。
            publish = button.filter(has_text="发表回复")
            if publish.count() > 0:
                button = publish
        except Exception:
            pass
        if button.count() == 0:
            button = surface.locator(
                'button:has-text("发表回复"), a:has-text("发表回复")'
            )
        if button.count() == 0:
            raise ActionUnavailable("没有找到「发表回复」按钮")
        before = self._reply_count(surface)
        try:
            button.first.click(timeout=5000)
        except Exception:
            self._dismiss(surface)
            button.first.click(timeout=5000)
        surface.wait_for_timeout(800)
        confirmed = self._wait_submitted(surface, before)
        close_modals(surface)
        return confirmed
