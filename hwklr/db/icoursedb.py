# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: icoursedb.py
# 主要用途: 中国大学慕课题库的 DbProvider：课程目录（id=0）与按 term_id 缓存的课程/测验/题目。
# 文件版本: 4.0.0
"""中国大学慕课题库提供者。

- ``id=0``：``hwklr/db/icourse_sources.json`` 的课程目录快照。
- ``id=term_id``：一门课程的题库记录，包含课程元信息与各测验的题目。

网络请求由 :class:`hwklr.db.icourse_client.GinsMoocClient` 完成；课程元信息
在缓存未命中的 ``fetch`` 中获取，题目由后台同步调用 :meth:`sync_test` 按测试
逐个抓取，网络请求都在 provider 锁之外完成，避免阻塞其他读取。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Final

from .icourse_client import GinsMoocClient, GinsMoocNotFound
from .icourse_models import (
    AnswerIndex,
    DbCourse,
    DbQuestion,
    DbTest,
    question_from_json,
)
from .provider import (
    DbFormatError,
    DbProvider,
    DbSourceNotFoundError,
    DbStorageError,
)

__version__ = "4.0.0"
__author__ = "Gary"
__all__ = ["CATALOG_ID", "IcourseDb", "course_questions", "record_answer_index"]

CATALOG_ID: Final[int] = 0
DEFAULT_TTL_SECONDS: Final[int] = 24 * 60 * 60
CATALOG_NAME: Final[str] = "icourse_sources.json"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def record_answer_index(record: dict[str, Any]) -> AnswerIndex:
    """从课程记录构建答案索引。

    Args:
        record: :class:`IcourseDb` 的课程 payload。

    Returns:
        包含所有已缓存题目的 :class:`AnswerIndex`。
    """
    questions: list[DbQuestion] = []
    tests: Any = record.get("tests")
    if isinstance(tests, dict):
        for entry in tests.values():
            if not isinstance(entry, dict):
                continue
            for item in entry.get("questions") or []:
                question = question_from_json(item)
                if question is not None:
                    questions.append(question)
    return AnswerIndex.from_questions(questions)


def course_questions(record: dict[str, Any], test_id: int) -> list[DbQuestion]:
    """从课程记录读取某个测验的题目。

    Args:
        record: :class:`IcourseDb` 的课程 payload。
        test_id: 测验 id。

    Returns:
        题目列表。
    """
    tests: Any = record.get("tests")
    entry: Any = tests.get(str(test_id)) if isinstance(tests, dict) else None
    if not isinstance(entry, dict):
        return []
    questions: list[DbQuestion] = []
    for item in entry.get("questions") or []:
        question = question_from_json(item)
        if question is not None:
            questions.append(question)
    return questions


class IcourseDb(DbProvider):
    """中国大学慕课题库提供者。"""

    def __init__(
        self,
        db_root: Path | None = None,
        source_root: Path | None = None,
        client: GinsMoocClient | None = None,
    ) -> None:
        """初始化题库 provider。

        Args:
            db_root: 数据库目录覆盖值（测试用）。
            source_root: 源描述目录覆盖值（测试用）。
            client: GinsMooc 客户端覆盖值（测试用）。
        """
        super().__init__("icourse", db_root=db_root, source_root=source_root)
        self._client: GinsMoocClient | None = client

    # ------------------------------------------------------------------ 基础
    @property
    def client(self) -> GinsMoocClient:
        """返回 GinsMooc 客户端（惰性创建）。

        Returns:
            :class:`GinsMoocClient`。
        """
        if self._client is None:
            self._client = GinsMoocClient()
        return self._client

    def _catalog(self) -> dict[str, Any]:
        """读取并校验内置课程目录。

        Returns:
            目录 JSON 对象。

        Raises:
            DbSourceNotFoundError: 目录文件不存在。
            DbFormatError: 目录结构不合法。
        """
        path: Path = self.source_root / CATALOG_NAME
        if not path.is_file():
            raise DbSourceNotFoundError("未找到慕课课程目录: %s" % path)
        try:
            with path.open(encoding="utf-8-sig") as handle:
                data: Any = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise DbFormatError("读取慕课课程目录失败: %s" % exc) from exc
        if not isinstance(data, dict) or not isinstance(data.get("courses"), list):
            raise DbFormatError("慕课课程目录缺少 courses 数组")
        return data

    def catalog_courses(self) -> list[dict[str, Any]]:
        """返回课程目录条目副本。

        Returns:
            ``[{id,name,school,image_url,...}]``。
        """
        courses = self._catalog().get("courses") or []
        return [dict(item) for item in courses if isinstance(item, dict)]

    def has_course(self, term_id: int) -> bool:
        """判断课程是否被题库目录收录。

        Args:
            term_id: 课程 term id。

        Returns:
            收录返回 ``True``。
        """
        try:
            courses = self.catalog_courses()
        except (DbSourceNotFoundError, DbFormatError):
            return False
        return any(_int_or_none(item.get("id")) == term_id for item in courses)

    # ------------------------------------------------------------------ fetch
    def fetch(self, id: int) -> dict[str, Any]:
        """读取目录或课程元信息。

        Args:
            id: ``0`` 表示目录；正数表示课程 term id。

        Returns:
            目录或课程 payload。

        Raises:
            DbSourceNotFoundError: 课程未收录。
            DbFormatError: 接口返回结构异常。
        """
        if id == CATALOG_ID:
            catalog: dict[str, Any] = self._catalog()
            courses: list[dict[str, Any]] = [
                dict(item)
                for item in catalog.get("courses") or []
                if isinstance(item, dict)
            ]
            return {
                "schema": 1,
                "base_name": self.base_name,
                "id": CATALOG_ID,
                "generated_at": str(catalog.get("generated_at") or ""),
                "count": len(courses),
                "items": courses,
            }

        if not self.has_course(id):
            raise DbSourceNotFoundError("题库未收录课程: %s" % id)
        course, tests = self.client.course_detail(id)
        if course is None:
            raise DbFormatError("题库返回的课程数据不完整: %s" % id)
        now: float = time.time()
        return {
            "schema": 1,
            "base_name": self.base_name,
            "id": id,
            "course": course.to_cache_dict(),
            "tests": {
                str(test.id): {
                    "meta": test.to_cache_dict(),
                    "questions": [],
                    "question_count": 0,
                    "fetched_at": 0.0,
                    "error": "",
                    "retry_after": 0.0,
                }
                for test in tests
            },
            "fetched_at": now,
            "ttl_seconds": DEFAULT_TTL_SECONDS,
        }

    # ------------------------------------------------------------------ 刷新
    def _load_existing(self, id: int) -> dict[str, Any] | None:
        """读取已有课程记录（不抛异常）。

        Args:
            id: 课程 term id。

        Returns:
            记录或 ``None``。
        """
        if not self.exist(id):
            return None
        try:
            return self.load(id)
        except Exception:
            return None

    def refresh_course(self, id: int, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict[str, Any]:
        """重新抓取课程元信息与测验列表。

        Args:
            id: 课程 term id。
            ttl_seconds: 写入记录中的 TTL。

        Returns:
            更新后的课程记录。

        Raises:
            DbSourceNotFoundError: 课程未收录。
            DbFormatError: 接口结构异常。
        """
        if not self.has_course(id):
            raise DbSourceNotFoundError("题库未收录课程: %s" % id)
        course, tests = self.client.course_detail(id)
        if course is None:
            raise DbFormatError("题库返回的课程数据不完整: %s" % id)
        existing: dict[str, Any] = self._load_existing(id) or {}
        existing_tests: Any = existing.get("tests")
        tests_payload: dict[str, Any] = (
            dict(existing_tests) if isinstance(existing_tests, dict) else {}
        )
        valid_ids: set[str] = {str(test.id) for test in tests}
        for stale in [key for key in tests_payload if key not in valid_ids]:
            tests_payload.pop(stale, None)
        for test in tests:
            entry: Any = tests_payload.get(str(test.id))
            if not isinstance(entry, dict):
                entry = {}
            entry["meta"] = test.to_cache_dict()
            entry.setdefault("questions", [])
            entry.setdefault("question_count", len(entry.get("questions") or []))
            entry.setdefault("fetched_at", 0.0)
            entry.setdefault("error", "")
            entry.setdefault("retry_after", 0.0)
            tests_payload[str(test.id)] = entry
        payload: dict[str, Any] = {
            "schema": 1,
            "base_name": self.base_name,
            "id": id,
            "course": course.to_cache_dict(),
            "tests": tests_payload,
            "fetched_at": time.time(),
            "ttl_seconds": int(ttl_seconds),
        }
        with self._guard():
            self._dump(id, payload)
        return payload

    def sync_test(
        self,
        id: int,
        test_id: int,
        *,
        force: bool = False,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> dict[str, Any]:
        """抓取并缓存单个测验的题目。

        网络请求在锁外完成；只有合并与落盘短暂持有 provider 锁。

        Args:
            id: 课程 term id。
            test_id: 测验 id。
            force: 忽略 TTL 强制刷新。
            ttl_seconds: TTL。

        Returns:
            更新后的课程记录。

        Raises:
            DbSourceNotFoundError: 课程未收录。
            GinsMoocError: 题库接口错误。
        """
        record: dict[str, Any] = self._load_existing(id) or self.refresh_course(
            id, ttl_seconds=ttl_seconds
        )
        tests: Any = record.get("tests")
        entry: Any = tests.get(str(test_id)) if isinstance(tests, dict) else None
        if not isinstance(entry, dict):
            entry = {
                "meta": {},
                "questions": [],
                "question_count": 0,
                "fetched_at": 0.0,
                "error": "",
                "retry_after": 0.0,
            }
            record.setdefault("tests", {})[str(test_id)] = entry
        first_fetched: float = float(entry.get("fetched_at") or 0)
        if (
            not force
            and entry.get("questions")
            and time.time() - first_fetched < max(0, ttl_seconds)
        ):
            return record
        retry_after: float = float(entry.get("retry_after") or 0)
        if not force and retry_after > time.time():
            return record
        try:
            questions: list[DbQuestion] = self.client.test_questions(test_id)
        except GinsMoocNotFound as exc:
            entry["error"] = str(exc)
            entry["retry_after"] = time.time() + 6 * 60 * 60
            with self._guard():
                self._dump(id, record)
            raise
        entry["questions"] = [question.to_cache_dict() for question in questions]
        entry["question_count"] = len(questions)
        entry["fetched_at"] = time.time()
        entry["error"] = ""
        entry["retry_after"] = 0.0
        record["fetched_at"] = time.time()
        record["ttl_seconds"] = int(ttl_seconds)
        with self._guard():
            self._dump(id, record)
        return record

    def bank_info(self) -> list[dict[str, Any]]:
        """返回设置页展示用的题库信息。

        Returns:
            单行目录信息；目录缺失时返回空列表。
        """
        try:
            catalog: dict[str, Any] = self._catalog()
        except (DbSourceNotFoundError, DbFormatError):
            return []
        courses: list[Any] = catalog.get("courses") or []
        return [
            {
                "feature": self.base_name,
                "version": "4.0",
                "count": len(courses),
            }
        ]
