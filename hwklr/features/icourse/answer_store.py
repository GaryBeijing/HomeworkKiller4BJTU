# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: answer_store.py
# 主要用途: 把 IcourseDb 的课程记录适配为动作层需要的答案索引与题库同步接口。
# 文件版本: 4.0.0
"""答案题库适配层。"""
from __future__ import annotations

from typing import Any

from hwklr.db.icourse_models import AnswerIndex
from hwklr.db.icoursedb import (
    DEFAULT_TTL_SECONDS,
    IcourseDb,
    course_questions,
    record_answer_index,
)

__version__ = "4.0.0"
__author__ = "Gary"
__all__ = ["AnswerStore"]


class AnswerStore:
    """动作层使用的题库缓存接口。"""

    def __init__(
        self,
        db: IcourseDb,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        """初始化适配层。

        Args:
            db: 慕课题库 provider。
            ttl_seconds: 题目缓存有效期。
        """
        self._db: IcourseDb = db
        self._ttl: int = max(1, int(ttl_seconds))

    def catalog(self) -> list[dict[str, Any]]:
        """返回课程目录条目。

        Returns:
            课程目录列表。
        """
        return self._db.catalog_courses()

    def has_course(self, term_id: int) -> bool:
        """判断课程是否被题库收录。

        Args:
            term_id: 课程 term id。

        Returns:
            收录返回 ``True``。
        """
        return self._db.has_course(int(term_id))

    def course_record(self, term_id: int, *, refresh: bool = False) -> dict[str, Any]:
        """读取课程题库记录；缺失时抓取元信息。

        Args:
            term_id: 课程 term id。
            refresh: 是否强制刷新课程元信息。

        Returns:
            课程记录。
        """
        if refresh or not self._db.exist(int(term_id)):
            return self._db.refresh_course(int(term_id), ttl_seconds=self._ttl)
        return self._db.load(int(term_id))

    def ensure_test(
        self, term_id: int, test_id: int, *, refresh: bool = False
    ) -> dict[str, Any]:
        """确保指定测验的题目已缓存。

        Args:
            term_id: 课程 term id。
            test_id: 测验 id。
            refresh: 是否强制刷新。

        Returns:
            更新后的课程记录。
        """
        self.course_record(term_id)
        return self._db.sync_test(
            int(term_id), int(test_id), force=refresh, ttl_seconds=self._ttl
        )

    def answer_index(
        self, term_id: int, test_id: int, *, refresh: bool = False
    ) -> AnswerIndex:
        """构建指定测验的答案索引。

        Args:
            term_id: 课程 term id。
            test_id: 测验 id。
            refresh: 是否强制刷新题目。

        Returns:
            :class:`AnswerIndex`。
        """
        record: dict[str, Any] = self.ensure_test(
            term_id, test_id, refresh=refresh
        )
        return AnswerIndex.from_questions(course_questions(record, int(test_id)))

    def all_questions_index(self, term_id: int) -> AnswerIndex:
        """基于已缓存的全部题目构建索引（用于视频弹题）。

        Args:
            term_id: 课程 term id。

        Returns:
            :class:`AnswerIndex`；未缓存时为空索引。
        """
        if not self._db.exist(int(term_id)):
            return AnswerIndex.from_questions(())
        try:
            record: dict[str, Any] = self._db.load(int(term_id))
        except Exception:
            return AnswerIndex.from_questions(())
        return record_answer_index(record)
