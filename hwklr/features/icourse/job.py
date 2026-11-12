# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-12 13:00
# 文件名: job.py
# 主要用途: 编排“开始完成”后台任务：视频并发、文档/测验/讨论串行、进度快照与取消。
# 文件版本: 4.6.1
"""完成任务的 job 编排。"""
from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Final

from hwklr.contracts import JobKind
from hwklr.db.icoursedb import IcourseDb
from hwklr.features.jobs import BackgroundJob

from . import config
from .actions import (
    ActionCancelled,
    ActionContext,
    ActionUnavailable,
    run_workers,
)
from .actions.base import safe_screenshot
from .answer_store import AnswerStore
from .browser_auth import export_saved_storage_state
from .browser_session import BrowserSession
from .client import AuthError, MoocClient
from .courses import reload_course
from .tasks import TaskHandlerRegistry, TaskOutcome, TaskStatus, default_task_registry
from .models import DONE, Course, Task

__version__ = "4.6.1"
__author__ = "Gary"
__all__ = ["CompletionJob"]

MAX_EVENTS: Final[int] = 200
Log = Callable[[str, str], None]

VIDEO_KIND = "视频"
DOCUMENT_KIND = "文档"
DISCUSSION_KIND = "讨论"
QUIZ_KINDS: Final[frozenset[str]] = frozenset({"测验", "随堂测验", "作业", "考试"})


class CompletionJob:
    """一次“开始完成”的后台任务。"""

    def __init__(
        self,
        course: Course,
        tasks: list[Task],
        *,
        client: MoocClient,
        db: IcourseDb,
        settings: dict[str, Any],
        log_callback: Log | None = None,
        handlers: TaskHandlerRegistry | None = None,
    ) -> None:
        """初始化任务。

        Args:
            course: 课程。
            tasks: 已勾选的任务（含唯一 key）。
            client: 已登录客户端。
            db: 慕课题库 provider。
            settings: 运行设置（workers/rate/submit 等）。
            log_callback: 日志回调 ``(level, message)``。
        """
        self.course: Course = course
        self.tasks: list[Task] = list(tasks)
        self._client: MoocClient = client
        self._db: IcourseDb = db
        self._settings: dict[str, Any] = dict(settings)
        self._handlers: TaskHandlerRegistry = handlers or default_task_registry()
        self._log_callback: Log = log_callback or (lambda level, message: None)
        self._job_id: str = uuid.uuid4().hex
        task_states: list[dict[str, Any]] = []
        for task in self.tasks:
            task_states.append({
                "key": task.key,
                "kind": task.kind,
                "title": task.name,
                "chapter": task.chapter,
                "lesson": task.lesson,
                "status": "等待队列",
                "percent": 0.0,
                "percent_text": "0%",
                "worker": -1,
                "attempts": 0,
                "error": "",
                "message": "",
                "started_at": 0.0,
                "finished_at": 0.0,
                "result": {},
                "score": None,
                "total_score": None,
                "score_text": "",
                "full_score": None,
                "screenshot": "",
            })
        self._job: BackgroundJob[None] = BackgroundJob(
            JobKind.COMPLETION,
            {
                "job_id": self._job_id,
                "running": False,
                "done": False,
                "cancelled": False,
                "phase": "idle",
                "message": "",
                "current": 0,
                "total": len(self.tasks),
                "term_id": course.term_id,
                "course_name": course.name,
                "workers": int(self._settings.get("workers", 8) or 8),
                "submit_quizzes": bool(self._settings.get("submit_quizzes")),
                "publish_discussions": bool(
                    self._settings.get("publish_discussions")
                ),
                "tasks": task_states,
                "events": [],
                "result": {"done": 0, "failed": 0, "skipped": 0, "cancelled": 0},
                "error": "",
            },
            include_job_id=True,
            max_events=MAX_EVENTS,
            log_callback=self._log_callback,
            job_id_factory=lambda: self._job_id,
        )
        self._updated_course: Course | None = None

    @property
    def job_id(self) -> str:
        """返回任务 ID。"""
        return self._job_id

    @property
    def background_job(self) -> BackgroundJob[None]:
        """返回底层通用 Job，供 JobStore 统一管理。"""
        return self._job

    @property
    def _cancel(self) -> Any:
        """兼容旧测试/调用方的取消事件访问。"""
        return self._job.cancel_event

    @property
    def _task_states(self) -> dict[str, dict[str, Any]]:
        """兼容旧测试/调用方：返回 key 到任务状态的映射副本。"""
        return {
            str(item.get("key") or ""): item
            for item in self._job.snapshot().get("tasks", [])
        }

    @property
    def updated_course(self) -> Course | None:
        """返回任务结束后重新拉取的课程状态。"""
        return self._updated_course

    # ------------------------------------------------------------------ 生命周期
    def start(self) -> dict[str, Any]:
        """启动后台线程并返回初始快照。

        Returns:
            初始快照。
        """
        return self._job.start(
            lambda job: self._run(),
            initial={
                "phase": "starting",
                "message": "正在准备完成课程任务…",
            },
        )

    def cancel(self) -> None:
        """请求取消。"""
        self._job.cancel_event.set()

    def join(self, timeout: float | None = None) -> None:
        """等待任务线程结束。"""
        self._job.join(timeout)

    def snapshot(self) -> dict[str, Any]:
        """返回深拷贝快照。

        Returns:
            任务快照。
        """
        return self._job.snapshot()

    def _update(self, **fields: Any) -> None:
        self._job.update_if(self.job_id, **fields)

    def _event(self, level: str, message: str, task: Task | None = None) -> None:
        self._job.event_if(self.job_id, level, message)

    def _set_task(self, task: Task, **fields: Any) -> None:
        def update(snapshot: dict[str, Any]) -> None:
            """在 Job 锁内更新单个任务状态。"""
            for state in snapshot.get("tasks", []):
                if state.get("key") == task.key:
                    state.update(fields)
                    return

        self._job.mutate_if(self.job_id, update)

    def _finish_task(
        self,
        task: Task,
        status: str,
        *,
        message: str = "",
        error: str = "",
        result: dict[str, Any] | None = None,
        score: float | None = None,
        total_score: float | None = None,
        score_text: str = "",
        full_score: bool | None = None,
        screenshot: str = "",
    ) -> None:
        completed: bool = status in ("完成", "已发布", "已填写")
        self._set_task(
            task,
            status=status,
            percent=100.0 if completed else 0.0,
            percent_text="100%" if completed else "0%",
            message=message,
            error=error,
            finished_at=time.time(),
            result=result or {},
            score=score,
            total_score=total_score,
            score_text=score_text,
            full_score=full_score,
            screenshot=screenshot,
        )
        detail: str = message or error
        self._event(
            "error" if status == "失败" else "info",
            "%s：%s%s" % (task.name, status, ("（%s）" % detail) if detail else ""),
        )

    # ------------------------------------------------------------------ 执行
    def _run(self) -> None:
        try:
            self._run_phases()
        except ActionCancelled as exc:
            self._cancel_remaining(str(exc))
            self._update(
                running=False,
                done=True,
                cancelled=True,
                phase="cancelled",
                message="任务已取消",
                error=str(exc),
            )
        except Exception as exc:
            self._cancel_remaining(str(exc))
            self._update(
                running=False,
                done=True,
                phase="error",
                message="任务失败：%s" % exc,
                error=str(exc),
            )
            self._event("error", "任务失败：%s" % exc)

    def _run_phases(self) -> None:
        settings: dict[str, Any] = self._settings
        ttl_seconds: int = max(1, int(settings.get("answer_ttl_hours", 24))) * 3600
        store = AnswerStore(self._db, ttl_seconds)

        batched: dict[Any, list[Task]] = {}
        serial_tasks: list[Task] = []
        for task in self.tasks:
            handler = self._handlers.for_kind(task.kind)
            if handler is None:
                self._finish_task(task, "已跳过", message="暂不支持该任务类型")
                continue
            if handler.batched:
                batched.setdefault(handler, []).append(task)
            else:
                serial_tasks.append(task)

        if self._cancel.is_set():
            raise ActionCancelled("任务已取消。")

        self._update(phase="db", message="正在检查题库…")
        try:
            store.course_record(self.course.term_id)
        except Exception as exc:
            self._event("warn", "题库检查失败，将继续执行不含答案的任务：%s" % exc)

        # 并发 handler（视频）先执行；串行 handler 再按任务顺序执行。
        for handler in self._handlers.all():
            tasks = batched.get(handler)
            if tasks and handler.batched:
                handler.run_batch(self, self.course, tasks, store, ttl_seconds)

        if serial_tasks:
            self._run_serial(serial_tasks, store)

        self._update(phase="verifying", message="正在刷新课程状态…")
        try:
            self._updated_course = reload_course(
                self._client,
                self.course,
                spoc_session=config.spoc_session_file(),
            )
        except Exception as exc:
            self._event("warn", "刷新课程状态失败：%s" % exc)
        if self._updated_course is not None:
            self._reconcile_failed_tasks(self._updated_course)

        done_count: int = sum(
            1
            for state in self._task_states.values()
            if state["status"] in ("完成", "已发布", "已填写")
        )
        failed_count: int = sum(
            1 for state in self._task_states.values() if state["status"] == "失败"
        )
        skipped_count: int = sum(
            1 for state in self._task_states.values() if state["status"] == "已跳过"
        )
        cancelled_count: int = sum(
            1 for state in self._task_states.values() if state["status"] == "已取消"
        )
        self._update(
            running=False,
            done=True,
            cancelled=bool(self._cancel.is_set()),
            phase="cancelled" if self._cancel.is_set() else "done",
            message="已完成 %d 个任务" % done_count,
            current=done_count + failed_count,
            result={
                "done": done_count,
                "failed": failed_count,
                "skipped": skipped_count,
                "cancelled": cancelled_count,
            },
        )

    # ------------------------------------------------------------------ 视频
    def _play_videos(
        self, videos: list[Task], store: AnswerStore, ttl_seconds: int
    ) -> None:
        self._update(phase="video", message="正在播放视频…")
        try:
            state = export_saved_storage_state(config.storage_state_file())
            storage_state = str(state)
        except Exception as exc:
            for task in videos:
                self._finish_task(task, "失败", error="缺少登录态：%s" % exc)
            return
        answer_index = store.all_questions_index(self.course.term_id)

        def on_start(task: Task, worker_id: int) -> None:
            self._set_task(
                task,
                status="进行中",
                worker=worker_id,
                started_at=time.time(),
            )

        def on_progress(
            task: Task,
            percent: float,
            _current: float,
            _duration: float,
            worker_id: int,
        ) -> None:
            self._set_task(
                task,
                status="进行中",
                percent=max(0.0, min(100.0, percent)),
                percent_text="%d%%" % int(max(0.0, min(100.0, percent))),
                worker=worker_id,
            )

        def on_done(task: Task, progress: Any, _worker_id: int) -> None:
            if progress.finished:
                self._finish_task(
                    task,
                    "完成",
                    result={"url": progress.url, "elapsed": round(progress.elapsed, 1)},
                )
            else:
                self._finish_task(
                    task,
                    "失败",
                    message=progress.reason,
                    error=progress.reason or "视频未完成",
                )

        def on_error(task: Task, message: str, _worker_id: int) -> None:
            if self._cancel.is_set():
                self._finish_task(task, "已取消", message="任务已取消")
            else:
                self._finish_task(task, "失败", error=message)

        try:
            batch = run_workers(
                self.course,
                videos,
                workers=int(self._settings.get("workers", 8) or 8),
                answer_index=answer_index,
                storage_state=storage_state,
                rate=float(self._settings.get("video_rate", 2.0) or 2.0),
                retain_data=bool(self._settings.get("retain_data", True)),
                log_callback=self._log_callback,
                cancel_event=self._cancel,
                on_task_start=on_start,
                on_progress=on_progress,
                on_task_done=on_done,
                on_task_error=on_error,
            )
        except Exception as exc:
            self._event("error", "视频阶段失败：%s" % exc)
            batch = None
        processed = {
            task.key
            for task in videos
            if self._task_states.get(task.key, {}).get("status") not in ("等待队列", "进行中")
        }
        for task in videos:
            if task.key not in processed:
                self._finish_task(
                    task,
                    "已取消" if self._cancel.is_set() else "失败",
                    error="任务未执行" if not self._cancel.is_set() else "任务已取消",
                )

    # ------------------------------------------------------------------ 串行
    def _run_serial(self, tasks: list[Task], store: AnswerStore) -> None:
        try:
            state = export_saved_storage_state(config.storage_state_file())
        except Exception as exc:
            for task in tasks:
                self._finish_task(task, "失败", error="缺少登录态：%s" % exc)
            return
        try:
            with BrowserSession(
                headless=True, attach=False, storage_state=str(state)
            ) as session:
                for task in tasks:
                    if self._cancel.is_set():
                        self._finish_task(task, "已取消", message="任务已取消")
                        continue
                    # 关键步骤：每个串行任务使用独立 Page，避免上一任务导航/弹窗
                    # 污染页面状态，导致后续文档或讨论连续失败。
                    page = session.new_page()
                    ctx = ActionContext(
                        session=session,
                        repository=store,
                        page=page,
                        interactive=False,
                        log_callback=self._log_callback,
                        cancel_event=self._cancel,
                        retain_data=bool(self._settings.get("retain_data", True)),
                    )
                    try:
                        self._run_one_serial(ctx, task, store)
                    finally:
                        try:
                            page.close()
                        except Exception:
                            pass
                        if ctx.page is not None and ctx.page is not page:
                            try:
                                ctx.page.close()
                            except Exception:
                                pass
        except Exception as exc:
            self._event("error", "串行阶段失败：%s" % exc)
            for task in tasks:
                state_info = self._task_states.get(task.key) or {}
                if state_info.get("status") in ("等待队列", "进行中"):
                    self._finish_task(task, "失败", error=str(exc))

    def _run_one_serial(
        self, ctx: ActionContext, task: Task, store: AnswerStore
    ) -> None:
        handler = self._handlers.for_kind(task.kind)
        if handler is None:
            self._finish_task(task, "已跳过", message="暂不支持该任务类型")
            return
        self._set_task(
            task,
            status="进行中",
            worker=0,
            started_at=time.time(),
            message="正在处理",
        )
        self._update(phase=handler.phase, message="正在处理：%s" % task.name)
        try:
            outcome: TaskOutcome = handler.run(
                self, ctx, self.course, task, store
            )
            self._apply_outcome(task, outcome)
        except ActionCancelled as exc:
            self._finish_task(task, "已取消", message=str(exc))
        except ActionUnavailable as exc:
            # 关键步骤：无法继续不等于用户取消；题库类任务仍按“跳过”展示。
            reason: str = self._error_text(exc)
            self._capture_failure(ctx, task)
            if task.kind in (DOCUMENT_KIND, DISCUSSION_KIND) and self._server_marked_done(task):
                status = "完成" if task.kind == DOCUMENT_KIND else "已发布"
                self._finish_task(
                    task,
                    status,
                    message="服务端已记录完成（原动作异常：%s）" % reason,
                )
            elif task.kind in QUIZ_KINDS:
                self._finish_task(task, "已跳过", message=reason)
            else:
                self._finish_task(task, "失败", error=reason)
        except AuthError as exc:
            self._capture_failure(ctx, task)
            self._finish_task(task, "失败", error=self._error_text(exc))
        except Exception as exc:
            self._capture_failure(ctx, task)
            reason = self._error_text(exc)
            if task.kind in (DOCUMENT_KIND, DISCUSSION_KIND) and self._server_marked_done(task):
                status = "完成" if task.kind == DOCUMENT_KIND else "已发布"
                self._finish_task(
                    task,
                    status,
                    message="服务端已记录完成（原动作异常：%s）" % reason,
                )
            else:
                self._finish_task(task, "失败", error=reason)

    def _apply_outcome(self, task: Task, outcome: TaskOutcome) -> None:
        """把 handler 的 TaskOutcome 写入任务状态。"""
        status: str = (
            outcome.status.value
            if isinstance(outcome.status, TaskStatus)
            else str(outcome.status)
        )
        self._finish_task(
            task,
            status,
            message=outcome.message,
            error=outcome.error,
            result=outcome.result,
            screenshot=outcome.screenshot,
            score=outcome.score,
            total_score=outcome.total_score,
            score_text=outcome.score_text,
            full_score=outcome.full_score,
        )

    def _server_marked_done(self, task: Task) -> bool:
        """动作异常后向服务端复核，避免把已完成的文档/讨论误报为失败。

        Args:
            task: 当前文档或讨论任务。

        Returns:
            服务端课程树中该任务已 ``DONE`` 时返回 ``True``。
        """
        if (
            task.kind == DISCUSSION_KIND
            and not self._settings.get("publish_discussions", False)
        ):
            # 未开启自动发布时，讨论只需要“已填写”；不能用服务端
            # done 状态把它误标成“已发布”。
            return False
        for attempt in range(3):
            try:
                fresh: Course = reload_course(
                    self._client,
                    self.course,
                    spoc_session=config.spoc_session_file(),
                )
            except Exception as exc:
                self._event("warn", "复核任务完成状态失败：%s" % exc)
                return False
            if not isinstance(fresh, Course):
                return False
            candidate = self._find_fresh_task(fresh, task)
            if candidate is not None:
                if candidate.status == DONE:
                    return True
            # 站点写学习状态有短暂延迟；失败后连续复核几次，避免
            # “动作报错但刷新后已完成”被误记为失败。
            if attempt < 2 and self._cancel.wait(1.2):
                return False
        return False

    @staticmethod
    def _find_fresh_task(fresh: Course, task: Task) -> Task | None:
        """在同一课程的新课程树中查找对应任务。"""
        for candidate in fresh.tasks:
            if candidate.kind != task.kind:
                continue
            if (
                task.unit_id
                and candidate.unit_id == task.unit_id
            ) or (
                task.content_id
                and candidate.content_id == task.content_id
            ):
                return candidate
        return None

    def _reconcile_failed_tasks(self, fresh: Course) -> None:
        """任务结束后用服务端状态修正“实际已完成但动作报错”的任务。

        Args:
            fresh: 任务结束后重新拉取的课程树。
        """
        if not isinstance(fresh, Course):
            return
        publish_discussions: bool = bool(
            self._settings.get("publish_discussions", False)
        )
        for task in self.tasks:
            state: dict[str, Any] = self._task_states.get(task.key) or {}
            if state.get("status") != "失败":
                continue
            if task.kind not in (DOCUMENT_KIND, DISCUSSION_KIND):
                continue
            if task.kind == DISCUSSION_KIND and not publish_discussions:
                continue
            candidate = self._find_fresh_task(fresh, task)
            if candidate is None or candidate.status != DONE:
                continue
            status: str = "完成" if task.kind == DOCUMENT_KIND else "已发布"
            self._finish_task(
                task,
                status,
                message="服务端已记录完成（任务结束后复核）",
            )

    @staticmethod
    def _capture_failure(ctx: ActionContext, task: Task) -> None:
        """在文档/讨论失败时保留现场截图，便于定位页面问题。"""
        if task.kind not in (DOCUMENT_KIND, DISCUSSION_KIND):
            return
        page = getattr(ctx, "page", None)
        if page is None:
            return
        prefix = "document" if task.kind == DOCUMENT_KIND else "discussion"
        identifier = task.unit_id or task.content_id or task.name
        safe_screenshot(ctx, page, f".artifacts/{prefix}-{identifier}-failed.png")

    @staticmethod
    def _error_text(exc: BaseException) -> str:
        """把异常压缩成适合 UI tooltip 的单行文本。

        Args:
            exc: 捕获到的异常。

        Returns:
            单行、限长的错误说明。
        """
        text: str = " ".join(str(exc or "").split())
        if not text:
            text = type(exc).__name__
        return text[:500]

    def _phase_for(self, task: Task) -> str:
        handler = self._handlers.for_kind(task.kind)
        return handler.phase if handler is not None else "serial"

    def _cancel_remaining(self, reason: str) -> None:
        for task in self.tasks:
            state = self._task_states.get(task.key) or {}
            if state.get("status") in ("等待队列", "进行中"):
                self._set_task(
                    task,
                    status="已取消",
                    error=reason,
                    finished_at=time.time(),
                )
