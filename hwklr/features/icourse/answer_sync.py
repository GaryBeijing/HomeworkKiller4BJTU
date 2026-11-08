# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: answer_sync.py
# 主要用途: 后台逐测验同步 GinsMooc 题库，提供进度快照与协作式取消。
# 文件版本: 4.0.0
"""题库后台同步。"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

from hwklr.db.icoursedb import IcourseDb

__version__ = "4.0.0"
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
        self._lock: threading.Lock = threading.Lock()
        self._cancel: threading.Event = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot: dict[str, Any] = {
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
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._snapshot.update(
                running=True,
                done=False,
                cancelled=False,
                current=0,
                cached=0,
                message="正在同步题库…",
                error="",
                started_at=time.time(),
                finished_at=0.0,
            )
            self._cancel.clear()
            self._thread = threading.Thread(
                target=self._run, name="icourse-answer-sync", daemon=True
            )
            self._thread.start()

    def cancel(self) -> None:
        """请求取消。"""
        self._cancel.set()

    def snapshot(self) -> dict[str, Any]:
        """返回同步快照。

        Returns:
            进度字典副本。
        """
        with self._lock:
            return dict(self._snapshot)

    def _update(self, **fields: Any) -> None:
        """更新快照字段。

        Args:
            **fields: 待更新字段。
        """
        with self._lock:
            self._snapshot.update(fields)

    def _run(self) -> None:
        """同步线程主体。"""
        cached: int = 0
        for index, test_id in enumerate(self._test_ids, 1):
            if self._cancel.is_set():
                break
            self._update(current=index, message="正在同步测验 %d/%d" % (index, len(self._test_ids)))
            try:
                self._db.sync_test(
                    self._term_id,
                    test_id,
                    force=self._force,
                    ttl_seconds=self._ttl,
                )
                cached += 1
                self._update(cached=cached)
            except Exception as exc:
                self._log("测验 %s 同步失败：%s" % (test_id, exc))
        cancelled: bool = self._cancel.is_set()
        self._update(
            running=False,
            done=True,
            cancelled=cancelled,
            message="同步已取消" if cancelled else "题库同步完成",
            finished_at=time.time(),
        )
