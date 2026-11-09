# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: job.py
# 主要用途: 编排“开始完成”后台任务：视频并发、文档/测验/讨论串行、进度快照与取消。
# 文件版本: 4.2.0
"""完成任务的 job 编排。"""
from __future__ import annotations

import copy
import threading
import time
import uuid
from typing import Any, Callable, Final

from hwklr.db.icoursedb import IcourseDb

from . import config
from .actions import (
    ActionCancelled,
    ActionContext,
    DiscussionAction,
    DocumentAction,
    QuizAction,
    run_workers,
)
from .answer_store import AnswerStore
from .browser_auth import export_saved_storage_state
from .browser_session import BrowserSession
from .client import AuthError, MoocClient
from .courses import reload_course
from .models import DONE, Course, Task

__version__ = "4.2.0"
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
        self.job_id: str = uuid.uuid4().hex
        self.course: Course = course
        self.tasks: list[Task] = list(tasks)
        self._client: MoocClient = client
        self._db: IcourseDb = db
        self._settings: dict[str, Any] = dict(settings)
        self._log_callback: Log = log_callback or (lambda level, message: None)
        self._lock: threading.Lock = threading.Lock()
        self._cancel: threading.Event = threading.Event()
        self._thread: threading.Thread | None = None
        self._task_states: dict[str, dict[str, Any]] = {}
        for task in self.tasks:
            self._task_states[task.key] = {
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
            }
        self._snapshot: dict[str, Any] = {
            "job_id": self.job_id,
            "running": False,
            "done": False,
            "cancelled": False,
            "phase": "idle",
            "message": "",
            "current": 0,
            "total": len(self.tasks),
            "term_id": course.term_id,
            "course_name": course.name,
            "workers": int(self._settings.get("workers", 1) or 1),
            "submit_quizzes": bool(self._settings.get("submit_quizzes")),
            "publish_discussions": bool(self._settings.get("publish_discussions")),
            "tasks": [],
            "events": [],
            "result": {"done": 0, "failed": 0, "skipped": 0, "cancelled": 0},
            "error": "",
        }
        self._updated_course: Course | None = None

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
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self.snapshot()
            self._snapshot.update(
                running=True,
                done=False,
                cancelled=False,
                phase="starting",
                message="正在准备完成课程任务…",
            )
            self._thread = threading.Thread(
                target=self._run, name="icourse-completion", daemon=True
            )
            self._thread.start()
            return self._snapshot_copy_locked()

    def cancel(self) -> None:
        """请求取消。"""
        self._cancel.set()

    def snapshot(self) -> dict[str, Any]:
        """返回深拷贝快照。

        Returns:
            任务快照。
        """
        with self._lock:
            return self._snapshot_copy_locked()

    def _snapshot_copy_locked(self) -> dict[str, Any]:
        data = copy.deepcopy(self._snapshot)
        data["tasks"] = [
            copy.deepcopy(self._task_states[task.key]) for task in self.tasks
        ]
        return data

    def _update(self, **fields: Any) -> None:
        with self._lock:
            self._snapshot.update(fields)

    def _event(self, level: str, message: str, task: Task | None = None) -> None:
        entry: dict[str, Any] = {
            "time": time.strftime("%H:%M:%S"),
            "message": message,
            "level": level,
        }
        with self._lock:
            events: list[dict[str, Any]] = self._snapshot["events"]
            events.append(entry)
            if len(events) > MAX_EVENTS:
                del events[: len(events) - MAX_EVENTS]
        self._log_callback(level, message)

    def _set_task(self, task: Task, **fields: Any) -> None:
        with self._lock:
            state: dict[str, Any] | None = self._task_states.get(task.key)
            if state is not None:
                state.update(fields)

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

        videos: list[Task] = [task for task in self.tasks if task.kind == VIDEO_KIND]
        documents: list[Task] = [task for task in self.tasks if task.kind == DOCUMENT_KIND]
        discussions: list[Task] = [task for task in self.tasks if task.kind == DISCUSSION_KIND]
        quizzes: list[Task] = [task for task in self.tasks if task.kind in QUIZ_KINDS]
        unsupported: list[Task] = [
            task
            for task in self.tasks
            if task.kind not in QUIZ_KINDS
            and task.kind not in (VIDEO_KIND, DOCUMENT_KIND, DISCUSSION_KIND)
        ]
        for task in unsupported:
            self._finish_task(task, "已跳过", message="暂不支持该任务类型")

        if self._cancel.is_set():
            raise ActionCancelled("任务已取消。")

        self._update(phase="db", message="正在检查题库…")
        try:
            store.course_record(self.course.term_id)
        except Exception as exc:
            self._event("warn", "题库检查失败，将继续执行不含答案的任务：%s" % exc)

        # ---------------------------------------------------------- 视频
        if videos:
            self._play_videos(videos, store, ttl_seconds)

        # ---------------------------------------------------------- 串行
        serial_tasks: list[Task] = [
            task
            for task in self.tasks
            if task.kind in (DOCUMENT_KIND, DISCUSSION_KIND) or task.kind in QUIZ_KINDS
        ]
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
                workers=int(self._settings.get("workers", 1) or 1),
                answer_index=answer_index,
                storage_state=storage_state,
                rate=float(self._settings.get("video_rate", 2.0) or 2.0),
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
                page = session.new_page()
                ctx = ActionContext(
                    session=session,
                    repository=store,
                    page=page,
                    interactive=False,
                    log_callback=self._log_callback,
                    cancel_event=self._cancel,
                )
                for task in tasks:
                    if self._cancel.is_set():
                        self._finish_task(task, "已取消", message="任务已取消")
                        continue
                    self._run_one_serial(ctx, task, store)
        except Exception as exc:
            self._event("error", "串行阶段失败：%s" % exc)
            for task in tasks:
                state_info = self._task_states.get(task.key) or {}
                if state_info.get("status") in ("等待队列", "进行中"):
                    self._finish_task(task, "失败", error=str(exc))

    def _run_one_serial(
        self, ctx: ActionContext, task: Task, store: AnswerStore
    ) -> None:
        self._set_task(
            task,
            status="进行中",
            worker=0,
            started_at=time.time(),
            message="正在处理",
        )
        self._update(phase=self._phase_for(task), message="正在处理：%s" % task.name)
        try:
            if task.kind == DOCUMENT_KIND:
                result = DocumentAction(ctx).run_one(
                    self.course,
                    task,
                    download=bool(self._settings.get("download_documents", True)),
                    dry_run=False,
                )
                self._finish_task(
                    task,
                    "完成",
                    message=result.message,
                    result={
                        "url": result.url,
                        "downloads": list(result.download_paths),
                        "verified": result.verified,
                    },
                )
                return
            if task.kind in QUIZ_KINDS:
                if not task.test_id:
                    self._finish_task(task, "已跳过", message="该任务没有测验 id")
                    return
                if self.course.is_spoc:
                    self._finish_task(task, "已跳过", message="刷题不支持 SPOC 课程")
                    return
                if not store.has_course(self.course.term_id):
                    self._finish_task(task, "已跳过", message="题库未收录该课程")
                    return
                submit: bool = bool(self._settings.get("submit_quizzes", False))
                result = QuizAction(ctx).run(
                    self.course,
                    task,
                    submit=submit,
                    apply=True,
                    refresh_db=bool(self._settings.get("refresh_quiz_db", False)),
                )
                screenshot: str = str(getattr(result, "screenshot", "") or "")
                score: float | None = getattr(result, "score", None)
                total_score: float | None = getattr(result, "total_score", None)
                score_text: str = str(getattr(result, "score_text", "") or "")
                full_score: bool | None = getattr(result, "full_score", None)
                base_result: dict[str, Any] = {
                    "url": result.url,
                    "matched": result.matched,
                    "applied": result.applied,
                    "submitted": result.submitted,
                    "screenshot": screenshot,
                }
                if submit and not result.submitted:
                    self._finish_task(task, "失败", error="测验提交失败")
                elif result.submitted:
                    self._finish_task(
                        task,
                        "完成",
                        message="已提交",
                        result={
                            **base_result,
                            "score": score,
                            "total_score": total_score,
                            "score_text": score_text,
                            "full_score": full_score,
                        },
                        score=score,
                        total_score=total_score,
                        score_text=score_text,
                        full_score=full_score,
                        screenshot=screenshot,
                    )
                else:
                    self._finish_task(
                        task,
                        "已填写",
                        message="已填写，未提交",
                        result=base_result,
                        screenshot=screenshot,
                    )
                return
            if task.kind == DISCUSSION_KIND:
                publish: bool = bool(self._settings.get("publish_discussions", False))
                result = DiscussionAction(ctx).run(
                    self.course, task, submit=publish, silent=False
                )
                screenshot = str(getattr(result, "screenshot", "") or "")
                if publish and not result.submitted:
                    self._finish_task(task, "失败", error="讨论发布失败")
                elif result.submitted:
                    self._finish_task(
                        task,
                        "已发布",
                        message="已发布",
                        result={
                            "url": result.url,
                            "submitted": True,
                            "screenshot": screenshot,
                        },
                        screenshot=screenshot,
                    )
                else:
                    self._finish_task(
                        task,
                        "已填写",
                        message="已填写，未发布",
                        result={
                            "url": result.url,
                            "submitted": False,
                            "screenshot": screenshot,
                        },
                        screenshot=screenshot,
                    )
                return
            self._finish_task(task, "已跳过", message="暂不支持该任务类型")
        except ActionCancelled as exc:
            self._finish_task(task, "已取消", message=str(exc))
        except AuthError as exc:
            self._finish_task(task, "失败", error=str(exc))
        except Exception as exc:
            self._finish_task(task, "失败", error=str(exc))

    @staticmethod
    def _phase_for(task: Task) -> str:
        if task.kind == DOCUMENT_KIND:
            return "document"
        if task.kind in QUIZ_KINDS:
            return "quiz"
        if task.kind == DISCUSSION_KIND:
            return "discussion"
        return "serial"

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
