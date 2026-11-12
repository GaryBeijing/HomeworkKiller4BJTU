# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-12 10:30
# 文件名: video.py
# 主要用途: 视频任务：播放、进度高水位、弹题与完成判定；截图受留存数据开关控制。
# 文件版本: 4.6.0
"""视频任务：从选中的一节开始，按顺序 2 倍速播放未完成视频。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from hwklr.db.icourse_models import AnswerIndex
from ..models import DONE, Course, Task
from ..pages import (
    close_modals,
    install_video_watch,
    learn_url,
    open_route,
    page_alerts,
    page_block_reason,
    seek_video,
    set_video_rate,
    video_state,
)
from .base import (
    ActionCancelled,
    ActionContext,
    SILENT_VIDEO_WARNING,
    safe_screenshot,
)
from .popup import PopupQuiz

VIDEO_KIND = "视频"
POLL_MS = 1500
MAX_WAIT_MS = 3 * 60 * 60 * 1000
# 距离结尾多少秒内视为播完；结束后播放器会把 currentTime 归零。
FINISH_TOLERANCE_SECONDS = 2.0
# 慕课视频没有心跳机制：直接拖到 99% 再等待播放完成。
SEEK_FRACTION = 0.99
# 跳转后要真正等到接近结尾，避免把 99% 误当成已完成。
SEEK_FINISH_TOLERANCE_SECONDS = 0.1
# 页面跳走/视频元素消失多久后放弃；避免登录态中途失效时卡满 3 小时。
MISSING_VIDEO_POLLS = 20
# 高水位多久没有增长就认为播放器卡死。
STALL_TIMEOUT_SECONDS = 300.0


def video_finished(
    state: dict,
    high_water: float = 0.0,
    tolerance: float = FINISH_TOLERANCE_SECONDS,
) -> bool:
    """判断一次视频轮询状态是否已播完（纯函数，便于单测）。

    判定顺序：
    1. 播放器的 ``ended``（或监听器记录的 ended）；
    2. 高水位（轮询值 + 页面监听记录的 max）到达 ``duration - tolerance``；
    3. 高水位接近结尾且 ``currentTime`` 已归零（结束后播放器重置）。
    """
    if not state or not state.get("ok"):
        return False
    if state.get("ended"):
        return True
    duration = float(state.get("duration") or 0)
    if duration <= 0:
        return False
    current = float(state.get("currentTime") or 0)
    high = max(
        high_water,
        float(state.get("max") or 0),
        current,
    )
    if high >= duration - tolerance:
        return True
    if current <= 1.0 and high >= duration - max(tolerance, 5.0):
        return True
    return False


@dataclass
class VideoProgress:
    task: Task
    url: str
    finished: bool
    reason: str = ""
    elapsed: float = 0.0
    max_current_time: float = 0.0
    final_state: dict = field(default_factory=dict)
    alerts: list[str] = field(default_factory=list)


def select_pending_videos(
    course: Course,
    *,
    start: Task | None = None,
    limit: int | None = None,
) -> list[Task]:
    all_tasks = course.tasks
    videos = [task for task in all_tasks if task.kind == VIDEO_KIND]
    if start is not None and start in all_tasks:
        begin = all_tasks.index(start)
        videos = [task for task in videos if all_tasks.index(task) >= begin]
    pending = [task for task in videos if task.status != DONE]
    if limit is not None:
        pending = pending[: max(0, limit)]
    return pending


ProgressCallback = Callable[[float, float, float], None]


class VideoAction:
    def __init__(
        self,
        ctx: ActionContext,
        answer_index: AnswerIndex | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.ctx = ctx
        self.answer_index = answer_index
        self.progress_callback = progress_callback

    def _report_progress(self, task: Task | None, state: dict) -> None:
        if self.progress_callback is None:
            return
        # 结束后播放器会把 currentTime 归零；用高水位避免面板从 100% 掉回 0%。
        current = max(
            float(state.get("currentTime") or 0),
            float(state.get("max") or 0),
        )
        duration = float(state.get("duration") or 0)
        percent = min(100.0, current * 100.0 / duration) if duration > 0 else 0.0
        try:
            self.progress_callback(percent, current, duration)
        except Exception:
            pass

    # ------------------------------------------------------------------ 入口
    def run(
        self,
        course: Course,
        *,
        start: Task | None = None,
        silent: bool = False,
        rate: float = 2.0,
        limit: int | None = None,
        max_seconds: float | None = None,
        tasks: list[Task] | None = None,
    ) -> list[VideoProgress]:
        if not course.school_short_name or not course.course_id:
            raise ActionCancelled("课程缺少 schoolShortName/courseId，无法构造学习页 URL")

        if tasks is not None:
            pending = [task for task in tasks if task.status != DONE]
            if limit is not None:
                pending = pending[: max(0, limit)]
        else:
            pending = select_pending_videos(course, start=start, limit=limit)

        if not pending:
            self.ctx.info("没有需要播放的未完成视频。")
            return []
        if silent:
            self.ctx.require_silent_consent(SILENT_VIDEO_WARNING)

        self.ctx.info(f"待播放视频 {len(pending)} 个，倍速 {rate:g}x。")
        results: list[VideoProgress] = []
        for index, task in enumerate(pending, 1):
            self.ctx.check_cancel()
            self.ctx.info(f"[{index}/{len(pending)}] {task.chapter} / {task.lesson} / {task.name}")
            progress = self._play_one(
                course, task, rate=rate, silent=silent, max_seconds=max_seconds
            )
            results.append(progress)
            status = "完成" if progress.finished else f"未完成（{progress.reason}）"
            self.ctx.log(f"  -> {status}，用时 {progress.elapsed:.0f}s")
        return results

    # ------------------------------------------------------------------ 单个
    def _play_one(
        self,
        course: Course,
        task: Task,
        *,
        rate: float,
        silent: bool,
        max_seconds: float | None = None,
    ) -> VideoProgress:
        self.ctx.check_cancel()
        if not task.lesson_id or not task.unit_id:
            return VideoProgress(task, "", False, "缺少 lessonId/unitId")
        base = learn_url(
            course.school_short_name,
            course.course_id,
            course.term_id,
            spoc=course.is_spoc,
        )
        hash_path = (
            f"#/learn/content?type=detail&id={task.lesson_id}&cid={task.unit_id}"
        )
        url = base + hash_path
        started = time.monotonic()
        page = self.ctx.acquire_page()
        open_route(page, base, hash_path)
        close_modals(page)
        blocked = page_block_reason(page)
        if blocked:
            safe_screenshot(
                self.ctx, page, f".artifacts/video-blocked-{task.unit_id}.png"
            )
            raise ActionCancelled(f"视频页无法访问：{blocked}。当前 URL：{page.url}")
        try:
            page.wait_for_selector("video", timeout=30_000)
        except Exception:
            safe_screenshot(
                self.ctx, page, f".artifacts/video-missing-{task.unit_id}.png"
            )
            return VideoProgress(task, url, False, "未找到 video 元素", time.monotonic() - started)

        if self.progress_callback is not None:
            try:
                self.progress_callback(0.0, 0.0, 0.0)
            except Exception:
                pass

        # 先挂 ended/timeupdate 监听，再开始播放；避免结束后 currentTime
        # 归零导致轮询永远看不到结尾。
        install_video_watch(page)
        # 视频元素可能还没进入可播放状态，重试几次。
        for _ in range(15):
            state = set_video_rate(page, rate=rate, muted=True)
            if state.get("ok") and state.get("readyState", 0) >= 1:
                break
            page.wait_for_timeout(1000)
        else:
            safe_screenshot(
                self.ctx, page, f".artifacts/video-notready-{task.unit_id}.png"
            )
            return VideoProgress(task, url, False, "视频未就绪", time.monotonic() - started)

        # 慕课视频没有心跳机制：直接拖到 99%，再等待播放完成。
        seeked = False
        seek_state = seek_video(page, SEEK_FRACTION)
        if seek_state.get("ok"):
            seeked = True
            self.ctx.info(
                "已将视频进度拖到 %.0f%%，等待播放完成。"
                % (float(seek_state.get("target") or 0) * 100.0 / max(1.0, float(seek_state.get("duration") or 1.0)))
            )
        else:
            self.ctx.warn(
                "无法跳转视频进度（%s），按正常播放等待。"
                % seek_state.get("reason", "unknown")
            )

        finished, reason, max_current = self._wait_silent(
            page,
            task,
            max_seconds=max_seconds,
            finish_tolerance=(
                SEEK_FINISH_TOLERANCE_SECONDS if seeked else FINISH_TOLERANCE_SECONDS
            ),
        )

        if finished:
            # 让播放器把最后一次进度心跳发出去，再暂停/离开。
            page.wait_for_timeout(1500)
        page.evaluate("() => { const v=document.querySelector('video'); if(v) v.pause(); }")
        final_state = video_state(page)
        max_current = max(
            max_current,
            float(final_state.get("currentTime") or 0),
            float(final_state.get("max") or 0),
        )
        if finished and self.progress_callback is not None:
            try:
                self.progress_callback(100.0, max_current, float(final_state.get("duration") or 0))
            except Exception:
                pass
        return VideoProgress(
            task,
            url,
            finished,
            reason,
            time.monotonic() - started,
            max_current,
            final_state,
            page_alerts(page),
        )

    # ------------------------------------------------------------------ 等待
    def _wait_silent(
        self,
        page,
        task: Task,
        *,
        max_seconds: float | None = None,
        finish_tolerance: float = FINISH_TOLERANCE_SECONDS,
    ) -> tuple[bool, str, float]:
        limit = MAX_WAIT_MS / 1000
        if max_seconds is not None:
            limit = min(limit, max(0.0, max_seconds))
        deadline = time.monotonic() + limit
        last_popup = ""
        max_current = 0.0
        last_progress_at = time.monotonic()
        missing_polls = 0
        while time.monotonic() < deadline:
            self.ctx.check_cancel()
            blocked = page_block_reason(page)
            if blocked:
                return False, f"页面跳转/登录失效：{blocked}", max_current
            if self._try_answer_popup(page):
                last_popup = ""
            popup = self._find_popup(page)
            if popup and popup != last_popup:
                last_popup = popup
                self.ctx.warn(f"检测到视频弹题/弹窗：{popup[:120]}")
                self._dismiss_popup(page)
            state = video_state(page)
            if not state.get("ok"):
                missing_polls += 1
                if missing_polls >= MISSING_VIDEO_POLLS:
                    return False, "视频元素消失或页面已跳转", max_current
                page.wait_for_timeout(POLL_MS)
                continue
            missing_polls = 0
            current = float(state.get("currentTime") or 0)
            previous = max_current
            max_current = max(
                max_current,
                current,
                float(state.get("max") or 0),
            )
            if max_current > previous + 0.5:
                last_progress_at = time.monotonic()
            elif time.monotonic() - last_progress_at >= STALL_TIMEOUT_SECONDS:
                return False, "长时间无进度", max_current
            self._report_progress(task, {**state, "currentTime": max_current})
            if video_finished(state, max_current, finish_tolerance):
                return True, "", max_current
            # 播放器被暂停且不是弹窗导致时，尝试恢复
            if state.get("paused") and not popup:
                page.evaluate("() => { const v=document.querySelector('video'); if(v) v.play().catch(()=>{}); }")
            page.wait_for_timeout(POLL_MS)
        return False, "等待超时", max_current

    # ------------------------------------------------------------------ 弹窗
    def _try_answer_popup(self, page) -> bool:
        if self.answer_index is None:
            return False
        popup = PopupQuiz(page, self.answer_index)
        if not popup.detect():
            return False
        answered = popup.answer()
        if popup.last_mode == "db":
            self.ctx.warn("检测到视频弹题，已按题库作答")
        elif popup.last_mode in ("A", "A-text"):
            self.ctx.warn("检测到视频弹题，题库未命中，已按 A 处理")
        else:
            self.ctx.warn("检测到视频弹题，未能自动作答")
        return answered

    @staticmethod
    def _find_popup(page) -> str:
        try:
            text = page.evaluate(
                """() => {
                  const sels = ['[class*=quizDialog]','[class*=QuizDialog]',
                    '[class*=questionDialog]','[class*=QuestionDialog]',
                    '[class*=popQuiz]','[class*=answerDialog]'];
                  for (const sel of sels) {
                    for (const el of document.querySelectorAll(sel)) {
                      const style = getComputedStyle(el);
                      if (style.display !== 'none' && style.visibility !== 'hidden'
                          && el.getBoundingClientRect().height > 0) {
                        return (el.innerText || '').trim().slice(0, 300);
                      }
                    }
                  }
                  return '';
                }"""
            )
        except Exception:
            return ""
        return text or ""

    def _dismiss_popup(self, page) -> None:
        # 目前只做保守处理：点击常见继续按钮。真正的答题逻辑在后续版本接入题库。
        try:
            page.evaluate(
                """() => {
                  const labels = ['继续','继续播放','确定','知道了','关闭'];
                  const nodes = [...document.querySelectorAll('button,a,span,div')];
                  for (const node of nodes) {
                    const text = (node.innerText || '').trim();
                    if (labels.includes(text) && node.getBoundingClientRect().height > 0) {
                      node.click();
                      return text;
                    }
                  }
                  return '';
                }"""
            )
        except Exception:
            pass
