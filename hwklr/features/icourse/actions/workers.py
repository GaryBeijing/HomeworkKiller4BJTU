# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-08 16:25
# 文件名: workers.py
# 主要用途: 并发视频 worker 调度与状态记录；已移除 rich 控制台渲染，改为回调与取消事件。
# 文件版本: 4.0.0
"""并发视频 worker。

调度规则：所有 worker 共享一个从上到下的扫描器，每次领取「已勾选且未完成」
的下一个视频；播放结束后继续领取，没有任务时结束。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..browser_session import BrowserSession, BrowserSessionError
from hwklr.db.icourse_models import AnswerIndex
from ..models import DONE, Course, Task
from .base import ActionContext
from .video import VideoAction, VideoProgress

MAX_WORKERS = 8
STATUS_INTERVAL_SECONDS = 3.0
RENDER_POLL_SECONDS = 0.25
FETCHING_NEXT_SECONDS = 1.0
NAME_LIMIT = 5

LogCallback = Callable[[str, str], None]
TaskCallback = Callable[..., None]


def short_course_name(name: str, limit: int = NAME_LIMIT) -> str:
    """截短课程名。

    Args:
        name: 课程名。
        limit: 最大字符数。

    Returns:
        截短后的名称。
    """
    text = str(name or "").strip()
    if not text:
        return "-"
    return text if len(text) <= limit else text[:limit] + "..."


@dataclass
class WorkerState:
    """单个 worker 的当前状态。"""

    worker_id: int
    state: str = "looking up"
    percent: float = 0.0
    task: str = ""
    course: str = ""
    error: str = ""
    fetching_until: float = 0.0

    @property
    def label(self) -> str:
        """返回可读状态。"""
        if self.state == "processing":
            return f"processing {self.percent:.0f}%"
        return self.state

    def is_fetching(self, now: float) -> bool:
        """是否处于「领取下一个」窗口。"""
        return now < self.fetching_until


class WorkerDashboard:
    """线程安全的 worker 状态表。"""

    def __init__(self, workers: int, course_name: str = "") -> None:
        """初始化状态表。

        Args:
            workers: worker 数量。
            course_name: 课程名。
        """
        self._lock: threading.Lock = threading.Lock()
        self._wake: threading.Event = threading.Event()
        self._rev: int = 0
        self._states: dict[int, WorkerState] = {
            index: WorkerState(worker_id=index, course=course_name)
            for index in range(workers)
        }

    def update(
        self,
        worker_id: int,
        *,
        state: str | None = None,
        percent: float | None = None,
        task: str | None = None,
        course: str | None = None,
        error: str | None = None,
    ) -> None:
        """更新 worker 状态。"""
        with self._lock:
            item: WorkerState = self._states.setdefault(
                worker_id, WorkerState(worker_id=worker_id)
            )
            if state is not None:
                item.state = state
            if percent is not None:
                item.percent = max(0.0, min(100.0, percent))
            if task is not None:
                item.task = task
            if course is not None:
                item.course = course
            if error is not None:
                item.error = error

    def finish_video(
        self,
        worker_id: int,
        *,
        error: str | None = None,
        now: float | None = None,
        seconds: float = FETCHING_NEXT_SECONDS,
    ) -> None:
        """标记视频结束后的短暂状态窗口。"""
        moment: float = time.monotonic() if now is None else now
        with self._lock:
            item: WorkerState = self._states.setdefault(
                worker_id, WorkerState(worker_id=worker_id)
            )
            item.state = "looking up"
            item.percent = 0.0
            item.fetching_until = moment + seconds
            if error is not None:
                item.error = error
            self._rev += 1
            self._wake.set()

    def snapshot(self) -> list[WorkerState]:
        """返回状态副本。"""
        with self._lock:
            return [
                WorkerState(
                    worker_id=item.worker_id,
                    state=item.state,
                    percent=item.percent,
                    task=item.task,
                    course=item.course,
                    error=item.error,
                    fetching_until=item.fetching_until,
                )
                for item in sorted(self._states.values(), key=lambda x: x.worker_id)
            ]

    def render_line(self, now: float | None = None) -> str:
        """返回原型风格的纯文本状态行（保留供测试/日志）。"""
        moment: float = time.monotonic() if now is None else now
        parts: list[str] = []
        for item in self.snapshot():
            label = f"T{item.worker_id + 1}"
            course = short_course_name(item.course)
            if item.state == "processing":
                text = f"{label}({course}): {item.percent:.0f}%"
            elif item.state == "done":
                text = f"{label}({course}): done"
            elif item.state == "error":
                text = f"{label}({course}): error"
            else:
                text = f"{label}({course}): looking up"
            if item.is_fetching(moment) and item.state not in ("done", "error"):
                text += " (fetching next)"
            parts.append(text)
        return "  ".join(parts)

    def revision(self) -> int:
        """返回状态版本号。"""
        with self._lock:
            return self._rev

    def wait_for_render(self, timeout: float) -> None:
        """等待状态变化（保留给旧调用方）。"""
        self._wake.wait(max(0.0, timeout))
        self._wake.clear()


class VideoScheduler:
    """从上到下领取未完成且未领取的视频。"""

    def __init__(self, tasks: list[Task]) -> None:
        """初始化调度器。

        Args:
            tasks: 视频任务列表。
        """
        self._tasks: list[Task] = list(tasks)
        self._index: int = 0
        self._claimed: set[int] = set()
        self._lock: threading.Lock = threading.Lock()

    def next(self) -> tuple[int, Task] | None:
        """领取下一个任务。

        Returns:
            ``(index, task)``；没有任务时返回 ``None``。
        """
        with self._lock:
            while self._index < len(self._tasks):
                index: int = self._index
                self._index += 1
                task: Task = self._tasks[index]
                if task.status == DONE or index in self._claimed:
                    continue
                self._claimed.add(index)
                return index, task
            return None

    def remaining(self) -> list[Task]:
        """返回尚未领取的任务。"""
        with self._lock:
            return [
                task
                for index, task in enumerate(self._tasks)
                if index not in self._claimed and task.status != DONE
            ]


@dataclass
class WorkerResult:
    """单个 worker 的执行结果。"""

    worker_id: int
    results: list[VideoProgress] = field(default_factory=list)
    error: str = ""
    started_at: float = 0.0
    elapsed: float = 0.0

    @property
    def played(self) -> int:
        """播放过的视频数量。"""
        return sum(1 for item in self.results if item.max_current_time >= 3)


@dataclass
class WorkerBatch:
    """一批 worker 的执行结果。"""

    workers: list[WorkerResult]
    unprocessed: list[Task]


def run_workers(
    course: Course,
    tasks: list[Task],
    *,
    workers: int = 4,
    answer_index: AnswerIndex | None = None,
    storage_state: Path | str | None = None,
    rate: float = 2.0,
    max_seconds: float | None = None,
    start_delay: float = 0.0,
    dashboard: WorkerDashboard | None = None,
    log_callback: LogCallback | None = None,
    cancel_event: threading.Event | None = None,
    on_task_start: Callable[[Task, int], None] | None = None,
    on_progress: Callable[[Task, float, float, float, int], None] | None = None,
    on_task_done: Callable[[Task, VideoProgress, int], None] | None = None,
    on_task_error: Callable[[Task, str, int], None] | None = None,
) -> WorkerBatch:
    """并发播放视频任务。

    Args:
        course: 课程。
        tasks: 待播放的视频任务。
        workers: 并发数（1–8）。
        answer_index: 弹题答案索引。
        storage_state: 无头登录态文件。
        rate: 播放倍速。
        max_seconds: 单个视频最长等待秒数。
        start_delay: worker 启动错峰秒数。
        dashboard: 状态表。
        log_callback: 日志回调。
        cancel_event: 取消事件。
        on_task_start: 任务开始回调。
        on_progress: 进度回调 ``(task, percent, current, duration, worker_id)``。
        on_task_done: 任务完成回调。
        on_task_error: 任务失败回调。

    Returns:
        :class:`WorkerBatch`。

    Raises:
        BrowserSessionError: 登录态文件缺失。
    """
    workers = max(1, min(int(workers), MAX_WORKERS))
    state: Path | None = Path(storage_state) if storage_state else None
    if state is not None and not state.is_file():
        raise BrowserSessionError("登录态文件不存在：%s" % state)

    scheduler = VideoScheduler(tasks)
    dashboard = dashboard or WorkerDashboard(workers, course_name=course.name)
    for index in range(workers):
        dashboard.update(index, state="looking up", percent=0, task="", course=course.name)

    worker_results: list[WorkerResult] = []
    collected: dict[int, VideoProgress | None] = {}
    lock: threading.Lock = threading.Lock()

    def runner(worker_id: int) -> None:
        result = WorkerResult(worker_id=worker_id)
        result.started_at = time.monotonic()
        if start_delay:
            time.sleep(worker_id * start_delay)
        try:
            with BrowserSession(
                headless=True, attach=False, storage_state=state
            ) as session:
                page = session.new_page()
                context = ActionContext(
                    session=session,
                    repository=None,
                    page=page,
                    interactive=False,
                    log_callback=log_callback,
                    cancel_event=cancel_event,
                )
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        break
                    dashboard.update(worker_id, state="looking up", percent=0)
                    claimed: tuple[int, Task] | None = scheduler.next()
                    if claimed is None:
                        dashboard.update(worker_id, state="done", percent=0)
                        break
                    index, task = claimed
                    if on_task_start is not None:
                        on_task_start(task, worker_id)
                    dashboard.update(
                        worker_id,
                        state="processing",
                        percent=0,
                        task=f"{task.chapter} / {task.name}",
                        course=course.name,
                    )

                    def progress_cb(
                        percent: float,
                        current: float,
                        duration: float,
                        *,
                        _wid: int = worker_id,
                        _task: Task = task,
                    ) -> None:
                        dashboard.update(
                            _wid,
                            state="processing",
                            percent=percent,
                            task=f"{_task.chapter} / {_task.name}",
                        )
                        if on_progress is not None:
                            on_progress(_task, percent, current, duration, _wid)

                    action = VideoAction(
                        context,
                        answer_index=answer_index,
                        progress_callback=progress_cb,
                    )
                    try:
                        progress: list[VideoProgress] = action.run(
                            course,
                            tasks=[task],
                            silent=True,
                            rate=rate,
                            max_seconds=max_seconds,
                        )
                        with lock:
                            collected[index] = progress[0] if progress else None
                            result.results.extend(progress)
                        if progress and on_task_done is not None:
                            on_task_done(task, progress[0], worker_id)
                    except Exception as exc:
                        message: str = str(exc)
                        dashboard.finish_video(worker_id, error=message)
                        if on_task_error is not None:
                            on_task_error(task, message, worker_id)
                    else:
                        dashboard.finish_video(worker_id)
        except Exception as exc:
            result.error = str(exc)
            dashboard.update(worker_id, state="error", error=str(exc))
            if log_callback is not None:
                log_callback("error", "视频 worker 启动失败：%s" % exc)
        finally:
            result.elapsed = time.monotonic() - result.started_at
            with lock:
                worker_results.append(result)

    threads: list[threading.Thread] = [
        threading.Thread(target=runner, args=(index,), name="icourse-video-%d" % index)
        for index in range(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return WorkerBatch(workers=worker_results, unprocessed=scheduler.remaining())
