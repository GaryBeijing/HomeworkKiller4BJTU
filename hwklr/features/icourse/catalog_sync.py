# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-16 20:30
# 最后更新: 2026-11-16 20:30
# 文件名: catalog_sync.py
# 主要用途: 后台刷新 GinsMooc 课程目录，写入可写增量并提供进度/取消。
# 文件版本: 4.6.7
"""课程目录后台刷新。"""
from __future__ import annotations

import time
from typing import Any, Callable

from hwklr.contracts import JobKind
from hwklr.db.icoursedb import IcourseDb
from hwklr.features.jobs import BackgroundJob

__version__ = "4.6.7"
__author__ = "Gary"
__all__ = ["CatalogRefreshJob"]

Log = Callable[[str], None]


class CatalogRefreshJob:
    """从 GinsMooc 分页拉取课程目录的后台任务。"""

    def __init__(
        self,
        db: IcourseDb,
        *,
        log: Log | None = None,
        on_success: Callable[[], None] | None = None,
    ) -> None:
        """初始化目录刷新任务。

        Args:
            db: 慕课题库 provider。
            log: 日志回调。
            on_success: 成功写入增量后的回调（用于清理目录缓存）。
        """
        self._db: IcourseDb = db
        self._log: Log = log or (lambda message: None)
        self._on_success = on_success or (lambda: None)
        self._job: BackgroundJob[None] = BackgroundJob(
            JobKind.CATALOG_REFRESH,
            self._idle_snapshot(),
            include_job_id=False,
        )

    @property
    def background_job(self) -> BackgroundJob[None]:
        """返回底层通用 Job，供 JobStore 统一管理。"""
        return self._job

    @staticmethod
    def _idle_snapshot() -> dict[str, Any]:
        """返回空闲快照形状。"""
        return {
            "running": False,
            "done": False,
            "cancelled": False,
            "page": 0,
            "total_pages": 0,
            "fetched": 0,
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
                "page": 0,
                "total_pages": 0,
                "fetched": 0,
                "message": "正在刷新课程目录…",
                "error": "",
                "started_at": time.time(),
                "finished_at": 0.0,
            },
        )

    def cancel(self) -> None:
        """请求取消。"""
        self._job.cancel()

    def snapshot(self) -> dict[str, Any]:
        """返回进度快照。"""
        return self._job.snapshot()

    def join(self, timeout: float | None = None) -> None:
        """等待刷新线程结束。"""
        self._job.join(timeout)

    def _run(self, job: BackgroundJob[None]) -> None:
        """刷新线程主体。"""
        def progress(page: int, total_pages: int, count: int) -> None:
            job.update(
                page=int(page),
                total_pages=int(total_pages),
                fetched=int(count),
                message=(
                    "正在刷新课程目录 %d/%d 页"
                    % (int(page), int(total_pages))
                    if total_pages
                    else "正在刷新课程目录…"
                ),
            )

        try:
            result: dict[str, Any] = self._db.refresh_catalog(
                progress=progress,
                cancelled=lambda: job.cancel_event.is_set(),
            )
        except Exception as exc:
            self._log("课程目录刷新失败：%s" % exc)
            job.update(
                running=False,
                done=True,
                error=str(exc),
                message="课程目录刷新失败，已保留旧目录",
                finished_at=time.time(),
            )
            return
        if result.get("cancelled"):
            job.update(
                running=False,
                done=True,
                cancelled=True,
                message="课程目录刷新已取消，未写入增量",
                finished_at=time.time(),
            )
            return
        try:
            self._on_success()
        except Exception:
            pass
        job.update(
            running=False,
            done=True,
            cancelled=False,
            fetched=int(result.get("count") or 0),
            page=int(result.get("pages") or 0),
            message="课程目录刷新完成，共 %d 门课程" % int(result.get("count") or 0),
            finished_at=time.time(),
        )
