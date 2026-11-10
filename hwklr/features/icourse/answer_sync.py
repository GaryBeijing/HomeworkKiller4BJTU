# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-10 23:59
# 文件名: answer_sync.py
# 主要用途: 后台逐测验同步 GinsMooc 题库，提供进度快照与协作式取消。
# 文件版本: 4.4.2
"""题库后台同步。"""
from __future__ import annotations

import time
from typing import Any, Callable

from hwklr.contracts import JobKind
from hwklr.db.icoursedb import IcourseDb
from hwklr.features.jobs import BackgroundJob

__version__ = "4.4.2"
__author__ = "Gary"
__all__ = ["AnswerSyncJob"]

Log = Callable[[str], None]


class AnswerSyncJob:
    """逐测验抓取题库的后台任务。"""

    def __init__(
        self,
        db: IcourseDb,
        term_id: int,
        test_ids: list[int],
        *,
        ttl_seconds: int = 24 * 60 * 60,
        log: Log | None = None,
        force: bool = False,
    ) -> None:
        """初始化同步任务。

        Args:
            db: 慕课题库 provider。
            term_id: 课程 term id。
            test_ids: 待同步测验 id 列表。
            ttl_seconds: 缓存有效期。
            log: 日志回调。
            force: 是否忽略缓存强制刷新。
        """
        self._db: IcourseDb = db
        self._term_id: int = int(term_id)
        self._test_ids: list[int] = [int(item) for item in test_ids]
        self._ttl: int = max(1, int(ttl_seconds))
        self._force: bool = bool(force)
        self._log: Log = log or (lambda message: None)
        self._job: BackgroundJob[None] = BackgroundJob(
            JobKind.ANSWER_SYNC,
            self._idle_snapshot(),
            include_job_id=False,
        )

    @property
    def background_job(self) -> BackgroundJob[None]:
        """返回底层通用 Job，供 JobStore 统一管理。"""
        return self._job

    def _idle_snapshot(self) -> dict[str, Any]:
        """返回同步快照初始形状。"""
        return {
            "running": False,
            "done": False,
            "cancelled": False,
            "term_id": self._term_id,
            "current": 0,
            "total": len(self._test_ids),
            "cached": 0,
            "total_tests": len(self._test_ids),
            "message": "",
            "error": "",
            "started_at": 0.0,
            "finished_at": 0.0,
        }

    def start(self) -> None:
        """启动后台线程（重复调用无效果）。"""
        self._job.start(
            self._run,
            initial={
                "current": 0,
                "cached": 0,
                "message": "正在同步题库…",
                "error": "",
                "started_at": time.time(),
                "finished_at": 0.0,
            },
        )

    def cancel(self) -> None:
        """请求取消。"""
        self._job.cancel()

    def snapshot(self) -> dict[str, Any]:
        """返回同步快照。

        Returns:
            进度字典副本。
        """
        return self._job.snapshot()

    def join(self, timeout: float | None = None) -> None:
        """等待同步线程结束。"""
        self._job.join(timeout)

    def _run(self, job: BackgroundJob[None]) -> None:
        """同步线程主体。"""
        cached: int = 0
        for index, test_id in enumerate(self._test_ids, 1):
            if job.cancel_event.is_set():
                break
            job.update(
                current=index,
                message="正在同步测验 %d/%d" % (index, len(self._test_ids)),
            )
            try:
                self._db.sync_test(
                    self._term_id,
                    test_id,
                    force=self._force,
                    ttl_seconds=self._ttl,
                )
                cached += 1
                job.update(cached=cached)
            except Exception as exc:
                self._log("测验 %s 同步失败：%s" % (test_id, exc))
        cancelled: bool = job.cancel_event.is_set()
        job.update(
            running=False,
            done=True,
            cancelled=cancelled,
            message="同步已取消" if cancelled else "题库同步完成",
            finished_at=time.time(),
        )
