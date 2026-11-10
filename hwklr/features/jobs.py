# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-10 11:00
# 文件名: jobs.py
# 主要用途: 通用后台 Job 基础设施：线程生命周期、快照深拷贝、事件环形缓冲与协作式取消。
# 文件版本: 4.4.0
"""后台 Job 基础设施。

各功能保留自己的 start/get/cancel 返回形状；本模块只统一内部生命周期，
避免每套 job 各自复制线程、锁、快照和取消代码。
"""
from __future__ import annotations

import copy
import threading
import time
import uuid
from typing import Any, Callable, Generic, TypeVar

from hwklr.contracts import JobKind

__version__ = "4.4.0"
__author__ = "Gary"
__all__ = ["BackgroundJob", "JobStore"]

R = TypeVar("R")
Runner = Callable[["BackgroundJob[Any]"], R]


class BackgroundJob(Generic[R]):
    """一个线程 + 一个快照 + 一个取消事件。"""

    def __init__(
        self,
        kind: JobKind,
        idle_snapshot: dict[str, Any],
        *,
        include_job_id: bool = True,
        max_events: int = 200,
        log_callback: Callable[[str, str], None] | None = None,
    ) -> None:
        """初始化 job。

        Args:
            kind: job 种类。
            idle_snapshot: 空闲快照；每次 start 会深拷贝它。
            include_job_id: 是否在快照中加入 ``job_id``。
            max_events: events 上限。
            log_callback: 可选 ``(level, message)`` 日志回调。
        """
        self.kind: JobKind = kind
        self._idle: dict[str, Any] = copy.deepcopy(idle_snapshot)
        self._include_job_id: bool = bool(include_job_id)
        self._max_events: int = max(1, int(max_events))
        self._log_callback = log_callback or (lambda level, message: None)
        self._lock: threading.RLock = threading.RLock()
        self._snapshot: dict[str, Any] = copy.deepcopy(self._idle)
        self._job_id: str = ""
        self._thread: threading.Thread | None = None
        self._cancel_event: threading.Event = threading.Event()

    @property
    def job_id(self) -> str:
        """返回当前 job id。"""
        with self._lock:
            return self._job_id

    @property
    def cancel_event(self) -> threading.Event:
        """返回协作式取消事件。"""
        return self._cancel_event

    @property
    def running(self) -> bool:
        """返回是否仍在运行。"""
        with self._lock:
            return bool(self._snapshot.get("running"))

    def start(
        self,
        runner: Runner,
        *,
        initial: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """启动线程；已运行时返回当前快照。

        Args:
            runner: 接收本 job 的运行函数。
            initial: 本次运行的初始快照字段。

        Returns:
            启动后的快照副本。
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return copy.deepcopy(self._snapshot)
            self._job_id = uuid.uuid4().hex
            self._snapshot = copy.deepcopy(self._idle)
            if self._include_job_id:
                self._snapshot["job_id"] = self._job_id
            if initial:
                self._snapshot.update(copy.deepcopy(initial))
            self._snapshot.update(running=True, done=False, cancelled=False)
            self._cancel_event = threading.Event()
            self._thread = threading.Thread(
                target=self._run,
                args=(runner,),
                name="hwklr-job-%s" % self.kind.value,
                daemon=True,
            )
            self._thread.start()
            return copy.deepcopy(self._snapshot)

    def _run(self, runner: Runner) -> None:
        """线程入口；未捕获异常写成 error 并结束。"""
        try:
            runner(self)
        except Exception as exc:
            with self._lock:
                self._snapshot.update(
                    running=False,
                    done=True,
                    error=str(exc),
                    message="任务失败：%s" % exc,
                    finished_at=time.time(),
                )
            self._log_callback("error", "后台任务失败：%s" % exc)
        finally:
            with self._lock:
                if self._snapshot.get("running"):
                    self._snapshot.update(
                        running=False,
                        done=True,
                        finished_at=time.time(),
                    )

    def snapshot(self) -> dict[str, Any]:
        """返回快照深拷贝。"""
        with self._lock:
            return copy.deepcopy(self._snapshot)

    def update(self, **fields: Any) -> None:
        """更新快照字段。"""
        with self._lock:
            self._snapshot.update(fields)

    def update_if(self, job_id: str, **fields: Any) -> bool:
        """仅当 job id 匹配时更新，避免旧线程覆盖新任务。"""
        with self._lock:
            if job_id and self._snapshot.get("job_id") != job_id:
                return False
            self._snapshot.update(fields)
            return True

    def event(self, level: str, message: str) -> None:
        """追加事件；快照没有 events 时忽略。"""
        with self._lock:
            events: Any = self._snapshot.get("events")
            if not isinstance(events, list):
                return
            events.append(
                {
                    "time": time.strftime("%H:%M:%S"),
                    "level": str(level),
                    "message": str(message),
                }
            )
            if len(events) > self._max_events:
                del events[: len(events) - self._max_events]
        self._log_callback(str(level), str(message))

    def cancel(self) -> None:
        """请求协作式取消。"""
        self._cancel_event.set()
        self.update(cancelled=True)

    def join(self, timeout: float | None = None) -> None:
        """等待线程结束。"""
        thread: threading.Thread | None
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)


class JobStore:
    """按名称管理多个 BackgroundJob。"""

    def __init__(self) -> None:
        self._jobs: dict[str, BackgroundJob[Any]] = {}
        self._lock: threading.RLock = threading.RLock()

    def put(self, key: str, job: BackgroundJob[Any]) -> None:
        """登记一个 job。"""
        with self._lock:
            self._jobs[str(key)] = job

    def get(self, key: str) -> BackgroundJob[Any] | None:
        """读取 job。"""
        with self._lock:
            return self._jobs.get(str(key))

    def remove(self, key: str) -> None:
        """移除 job。"""
        with self._lock:
            self._jobs.pop(str(key), None)

    def active(self, key: str) -> bool:
        """返回指定 job 是否仍在运行。"""
        job = self.get(key)
        return bool(job is not None and job.running)

    def cancel_all(self, timeout: float = 0.0) -> None:
        """取消并等待所有 job。"""
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel()
        for job in jobs:
            job.join(timeout)
