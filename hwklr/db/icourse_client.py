# -*- coding: utf-8 -*-
# 作者: Gary (Adapted from GinsMooc by gin)
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-16 20:30
# 文件名: icourse_client.py
# 主要用途: GinsMooc 题库 HTTP 客户端（课程目录搜索、课程/测验/题目读取与实时答案查询）。
# 文件版本: 4.6.7
"""GinsMooc HTTP 客户端。

本模块是 GinsMooc 公开 HTTP 接口的独立 Python 适配实现；
字段与端点参考 GinsMooc（©2022-2024 gin），归属说明见项目根目录 NOTICE。

接口特点（详见 docs/ginsmooc-api.md）：
- 无需登录、CORS 全开；
- 分页 0 基；
- 业务错误常以 HTTP 200 + body.status=500 返回。
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Iterable, Iterator

import requests

from .icourse_models import (
    DbCourse,
    DbQuestion,
    DbTest,
    QuestionType,
    course_from_json,
    question_from_json,
    test_from_json,
)

__version__ = "4.6.7"

DEFAULT_BASE_URL = "https://ginnnnnn.top/api"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


class GinsMoocError(Exception):
    """题库接口错误。"""


class GinsMoocNotFound(GinsMoocError):
    """课程/测验未收录或 ID 非法（body.status=500）。"""


class GinsMoocClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        session: requests.Session | None = None,
        timeout: float = 30.0,
        retries: int = 2,
        min_interval: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.timeout = timeout
        self.retries = max(0, retries)
        self.min_interval = max(0.0, min_interval)
        self._last_call = 0.0
        # requests.Session 与节流状态跨线程共享；串行化 HTTP 更安全。
        self._request_lock = threading.Lock()

    # ------------------------------------------------------------------ HTTP
    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _decode(self, response: requests.Response) -> Any:
        try:
            payload = response.json()
        except ValueError as exc:
            raise GinsMoocError(f"接口返回的不是 JSON（HTTP {response.status_code}）") from exc
        if not isinstance(payload, dict):
            raise GinsMoocError("接口返回格式异常")
        status = payload.get("status")
        if status == 200:
            return payload.get("data")
        message = str(payload.get("msg") or payload.get("message") or "未知错误")
        if status == 500:
            raise GinsMoocNotFound(message)
        raise GinsMoocError(message)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        with self._request_lock:
            return self._request_locked(method, url, **kwargs)

    def _request_locked(self, method: str, url: str, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                response = self.session.request(
                    method, url, timeout=self.timeout, **kwargs
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(0.8 * (attempt + 1))
                continue
            if response.status_code == 404:
                raise GinsMoocNotFound(f"接口不存在：{url}")
            try:
                return self._decode(response)
            except GinsMoocNotFound:
                raise
            except GinsMoocError as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(0.5 * (attempt + 1))
        raise GinsMoocError(f"请求失败：{last_error}")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def _post(self, path: str, data: dict[str, Any]) -> Any:
        return self._request(
            "POST",
            path,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    # ------------------------------------------------------------------ 课程
    def course_page(
        self,
        page: int = 0,
        *,
        search: str = "",
        cid: int | str | None = None,
    ) -> tuple[list[DbCourse], int]:
        """返回 (课程列表, totalPages)。

        Args:
            page: 0 基页码。
            search: 服务端课程名/学校搜索关键字。
            cid: 只查询指定课程 id。
        """
        params: dict[str, Any] = {"page": max(0, int(page))}
        if str(search or "").strip():
            params["search"] = str(search).strip()
        if cid is not None:
            params["cid"] = int(cid)
        data = self._get("/mooc/course", params) or {}
        courses = [
            course
            for course in (
                course_from_json(item) for item in (data.get("courseList") or [])
                if isinstance(item, dict)
            )
            if course is not None
        ]
        return courses, int(data.get("totalPages") or 0)

    def iter_courses(self) -> Iterator[DbCourse]:
        page = 0
        while True:
            courses, total_pages = self.course_page(page)
            if not courses:
                return
            yield from courses
            page += 1
            if total_pages and page >= total_pages:
                return

    def course_detail(self, cid: int | str) -> tuple[DbCourse | None, list[DbTest]]:
        data = self._get(f"/mooc/course/{int(cid)}") or {}
        course = course_from_json(data.get("course") or {})
        tests = [
            test
            for test in (
                test_from_json(item) for item in (data.get("testList") or [])
                if isinstance(item, dict)
            )
            if test is not None
        ]
        return course, tests

    # ------------------------------------------------------------------ 测验
    def test_page(
        self, tid: int | str, page: int = 0
    ) -> tuple[DbCourse | None, DbTest | None, list[DbQuestion], int]:
        data = self._get(f"/mooc/test/{int(tid)}", {"page": max(0, int(page))}) or {}
        course = course_from_json(data.get("course") or {})
        test = test_from_json(data.get("test") or {})
        questions = [
            question
            for question in (
                question_from_json(item) for item in (data.get("questionList") or [])
                if isinstance(item, dict)
            )
            if question is not None
        ]
        return course, test, questions, int(data.get("totalPages") or 0)

    def iter_test_questions(self, tid: int | str) -> Iterator[DbQuestion]:
        page = 0
        while True:
            _course, _test, questions, total_pages = self.test_page(tid, page)
            if not questions:
                return
            yield from questions
            page += 1
            if total_pages and page >= total_pages:
                return

    def test_questions(self, tid: int | str) -> list[DbQuestion]:
        return list(self.iter_test_questions(tid))

    def test_exists(self, tid: int | str) -> bool:
        data = self._get(f"/mooc/test/{int(tid)}", {"type": "isExisting"}) or {}
        return bool(data.get("existing"))

    def select_questions(
        self,
        tid: int | str,
        oid_list: Iterable[int] = (),
        title_list: Iterable[str] = (),
    ) -> dict[str, Any]:
        """按题目 ID / 题干精确取答案（与 GinsMooc 扩展一致）。"""
        data = self._post(
            f"/mooc/test/{int(tid)}",
            {
                "oidList": json.dumps(list(oid_list), ensure_ascii=False),
                "titleList": json.dumps(list(title_list), ensure_ascii=False),
            },
        )
        return data or {}

    # ------------------------------------------------------------------ 其他
    def notice(self, version: str = "v1.0.0") -> dict[str, Any]:
        return self._get("/mooc/notice/website", {"version": version}) or {}

    def search_courses(self, query: str, *, school: str = "") -> list[DbCourse]:
        """通过服务端搜索课程。

        Args:
            query: 课程名关键字。
            school: 可选学校过滤。

        Returns:
            匹配的课程列表；接口失败时返回空列表。
        """
        needle: str = str(query or "").strip().lower()
        if not needle:
            return []
        try:
            courses, _pages = self.course_page(0, search=str(query).strip())
        except GinsMoocError:
            return []
        result: list[DbCourse] = []
        for course in courses:
            haystack: str = f"{course.name} {course.school}".lower()
            if needle not in haystack:
                continue
            if school and str(school).strip().lower() not in course.school.lower():
                continue
            result.append(course)
        return result

    def find_course(self, query: str) -> DbCourse | None:
        """按课程名/学校查找课程。

        先使用服务端搜索；不可用时回退到原始分页本地过滤。
        """
        needle = str(query or "").strip().lower()
        if not needle:
            return None
        found: list[DbCourse] = self.search_courses(query)
        if found:
            return found[0]
        for course in self.iter_courses():
            haystack = f"{course.name} {course.school}".lower()
            if needle in haystack:
                return course
        return None


def normalize_type(value: Any) -> QuestionType | None:
    return QuestionType.parse(value)
