# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-10 12:00
# 最后更新: 2026-11-17 10:00
# 文件名: tasks.py
# 主要用途: icourse 任务执行契约与 TaskHandler registry：把 Job 的 kind 分支收敛为可注入的 handler。
# 文件版本: 4.7.0
"""icourse 任务执行契约与 handler registry。

Job 只负责阶段、快照、取消和状态落盘；具体任务类型由 TaskHandler 实现。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from hwklr.contracts import QUIZ_KINDS, TaskKind, TaskStatus

from .actions import DiscussionAction, DocumentAction, PeerReviewAction, QuizAction
from .actions.base import ActionCancelled, ActionUnavailable
from .answer_store import AnswerStore
from .models import DONE, Course, Task

__version__ = "4.6.5"
__author__ = "Gary"
__all__ = [
    "DocumentTaskHandler",
    "DiscussionTaskHandler",
    "HomeworkTaskHandler",
    "QuizTaskHandler",
    "TaskHandler",
    "TaskHandlerRegistry",
    "TaskOutcome",
    "VideoTaskHandler",
    "default_task_registry",
]


@dataclass
class TaskOutcome:
    """一个任务的执行结果。"""

    status: TaskStatus
    message: str = ""
    error: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    screenshot: str = ""
    score: float | None = None
    total_score: float | None = None
    score_text: str = ""
    full_score: bool | None = None


class TaskHandler(Protocol):
    """任务 handler 协议。"""

    kinds: frozenset[str]
    phase: str
    batched: bool

    def run(
        self,
        job: Any,
        ctx: Any,
        course: Course,
        task: Task,
        store: AnswerStore,
    ) -> TaskOutcome:
        """执行一个串行任务。"""
        ...

    def run_batch(
        self,
        job: Any,
        course: Course,
        tasks: list[Task],
        store: AnswerStore,
        ttl_seconds: int,
    ) -> None:
        """执行一批并发任务（目前只有视频使用）。"""
        ...


class DocumentTaskHandler:
    """文档任务。"""

    kinds = frozenset({TaskKind.DOCUMENT.value})
    phase = "document"
    batched = False

    def run(
        self, job: Any, ctx: Any, course: Course, task: Task, store: AnswerStore
    ) -> TaskOutcome:
        result = DocumentAction(ctx).run_one(
            course,
            task,
            download=bool(job._settings.get("download_documents", True)),
            dry_run=False,
        )
        return TaskOutcome(
            TaskStatus.COMPLETED,
            message=result.message,
            result={
                "url": result.url,
                "downloads": list(result.download_paths),
                "verified": result.verified,
            },
        )

    def run_batch(
        self,
        job: Any,
        course: Course,
        tasks: list[Task],
        store: AnswerStore,
        ttl_seconds: int,
    ) -> None:
        raise NotImplementedError("文档任务不支持批量执行")


class QuizTaskHandler:
    """测验/作业/考试任务。"""

    kinds = QUIZ_KINDS
    phase = "quiz"
    batched = False

    def run(
        self, job: Any, ctx: Any, course: Course, task: Task, store: AnswerStore
    ) -> TaskOutcome:
        if not task.test_id:
            return TaskOutcome(TaskStatus.SKIPPED, message="该任务没有测验 id")
        if course.is_spoc:
            return TaskOutcome(TaskStatus.SKIPPED, message="刷题不支持 SPOC 课程")
        if not store.has_course(course.term_id):
            try:
                test_available: bool = store.test_exists(task.test_id)
            except Exception:
                test_available = False
            if not test_available:
                return TaskOutcome(
                    TaskStatus.SKIPPED,
                    message="题库未收录该课程/测验",
                )
            ctx.info("课程目录未收录，但当前测验可用，继续尝试…")
        submit: bool = bool(job._settings.get("submit_quizzes", False))
        result = QuizAction(ctx).run(
            course,
            task,
            submit=submit,
            apply=True,
            refresh_db=bool(job._settings.get("refresh_quiz_db", False)),
        )
        screenshot: str = str(getattr(result, "screenshot", "") or "")
        score: float | None = getattr(result, "score", None)
        total_score: float | None = getattr(result, "total_score", None)
        score_text: str = str(getattr(result, "score_text", "") or "")
        full_score: bool | None = getattr(result, "full_score", None)
        base: dict[str, Any] = {
            "url": result.url,
            "matched": result.matched,
            "applied": result.applied,
            "submitted": result.submitted,
            "screenshot": screenshot,
        }
        if submit and not result.submitted:
            return TaskOutcome(TaskStatus.FAILED, error="测验提交失败")
        if result.submitted:
            return TaskOutcome(
                TaskStatus.COMPLETED,
                message="已提交",
                result={
                    **base,
                    "score": score,
                    "total_score": total_score,
                    "score_text": score_text,
                    "full_score": full_score,
                },
                screenshot=screenshot,
                score=score,
                total_score=total_score,
                score_text=score_text,
                full_score=full_score,
            )
        return TaskOutcome(
            TaskStatus.FILLED,
            message="已填写，未提交",
            result=base,
            screenshot=screenshot,
        )

    def run_batch(
        self,
        job: Any,
        course: Course,
        tasks: list[Task],
        store: AnswerStore,
        ttl_seconds: int,
    ) -> None:
        raise NotImplementedError("测验任务不支持批量执行")


class HomeworkTaskHandler:
    """作业任务：先走原作业流程，再尝试实验性自动互评。"""

    kinds = frozenset({TaskKind.HOMEWORK.value})
    phase = "quiz"
    batched = False

    def run(
        self, job: Any, ctx: Any, course: Course, task: Task, store: AnswerStore
    ) -> TaskOutcome:
        auto_review = bool(job._settings.get("auto_peer_review", True))
        quiz_outcome: TaskOutcome | None = None
        quiz_error: ActionUnavailable | None = None
        if task.status != DONE:
            try:
                quiz_outcome = QuizTaskHandler().run(job, ctx, course, task, store)
            except ActionCancelled:
                raise
            except ActionUnavailable as exc:
                quiz_error = exc
        if not auto_review or course.is_spoc:
            if quiz_error is not None:
                raise quiz_error
            if quiz_outcome is not None:
                return quiz_outcome
            return TaskOutcome(TaskStatus.SKIPPED, message="作业已完成")

        review = PeerReviewAction(ctx).run(course, task)
        review_payload = {
            "available": review.available,
            "attempted": review.attempted,
            "reviewed": review.reviewed,
            "comments": list(review.comments),
            "message": review.message,
        }
        if review.reviewed:
            message = "已互评 %d 份" % review.reviewed
            if quiz_outcome is not None and quiz_outcome.message:
                message = quiz_outcome.message + "；" + message
            result: dict[str, Any] = dict(quiz_outcome.result if quiz_outcome else {})
            result["peer_review"] = review_payload
            return TaskOutcome(
                TaskStatus.COMPLETED,
                message=message,
                result=result,
                screenshot=review.screenshot
                or (quiz_outcome.screenshot if quiz_outcome else ""),
                score=quiz_outcome.score if quiz_outcome else None,
                total_score=quiz_outcome.total_score if quiz_outcome else None,
                score_text=quiz_outcome.score_text if quiz_outcome else "",
                full_score=quiz_outcome.full_score if quiz_outcome else None,
            )
        if quiz_error is not None:
            raise quiz_error
        if quiz_outcome is not None:
            warning = review.message or "未检测到待互评作业"
            if quiz_outcome.message:
                quiz_outcome.message += "；" + warning
            else:
                quiz_outcome.message = warning
            return quiz_outcome
        return TaskOutcome(
            TaskStatus.SKIPPED,
            message=review.message or "未检测到待互评作业",
        )

    def run_batch(
        self,
        job: Any,
        course: Course,
        tasks: list[Task],
        store: AnswerStore,
        ttl_seconds: int,
    ) -> None:
        raise NotImplementedError("作业任务不支持批量执行")


class DiscussionTaskHandler:
    """讨论任务。"""

    kinds = frozenset({TaskKind.DISCUSSION.value})
    phase = "discussion"
    batched = False

    def run(
        self, job: Any, ctx: Any, course: Course, task: Task, store: AnswerStore
    ) -> TaskOutcome:
        publish: bool = bool(job._settings.get("publish_discussions", False))
        result = DiscussionAction(ctx).run(
            course, task, submit=publish, silent=False
        )
        screenshot = str(getattr(result, "screenshot", "") or "")
        message = str(getattr(result, "message", "") or "")
        base: dict[str, Any] = {
            "url": result.url,
            "submitted": bool(result.submitted),
            "fallback_reply": bool(getattr(result, "fallback_reply", False)),
            "screenshot": screenshot,
        }
        if publish and not result.submitted:
            return TaskOutcome(
                TaskStatus.FAILED,
                error=message or "讨论发布失败",
                result=base,
                screenshot=screenshot,
            )
        if result.submitted:
            return TaskOutcome(
                TaskStatus.PUBLISHED,
                message=message or "已发布",
                result=base,
                screenshot=screenshot,
            )
        return TaskOutcome(
            TaskStatus.FILLED,
            message=message or "已填写，未发布",
            result=base,
            screenshot=screenshot,
        )

    def run_batch(
        self,
        job: Any,
        course: Course,
        tasks: list[Task],
        store: AnswerStore,
        ttl_seconds: int,
    ) -> None:
        raise NotImplementedError("讨论任务不支持批量执行")


class VideoTaskHandler:
    """视频任务；并发执行仍复用现有 worker 实现。"""

    kinds = frozenset({TaskKind.VIDEO.value})
    phase = "video"
    batched = True

    def run(
        self, job: Any, ctx: Any, course: Course, task: Task, store: AnswerStore
    ) -> TaskOutcome:
        raise NotImplementedError("视频任务只支持批量执行")

    def run_batch(
        self,
        job: Any,
        course: Course,
        tasks: list[Task],
        store: AnswerStore,
        ttl_seconds: int,
    ) -> None:
        job._play_videos(tasks, store, ttl_seconds)


class TaskHandlerRegistry:
    """按任务类型查找 handler。"""

    def __init__(self, handlers: list[TaskHandler] | None = None) -> None:
        self._handlers: list[TaskHandler] = list(handlers or [])
        self._by_kind: dict[str, TaskHandler] = {}
        for handler in self._handlers:
            for kind in handler.kinds:
                self._by_kind[str(kind)] = handler

    def for_kind(self, kind: str) -> TaskHandler | None:
        """返回处理指定 kind 的 handler。"""
        return self._by_kind.get(str(kind))

    def all(self) -> list[TaskHandler]:
        """返回所有 handler（去重）。"""
        return list(self._handlers)


def default_task_registry() -> TaskHandlerRegistry:
    """构造默认的 icourse handler registry。"""
    return TaskHandlerRegistry(
        [
            VideoTaskHandler(),
            DocumentTaskHandler(),
            QuizTaskHandler(),
            HomeworkTaskHandler(),
            DiscussionTaskHandler(),
        ]
    )
