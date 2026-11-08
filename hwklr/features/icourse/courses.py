# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: courses.py
# 主要用途: 获取课程列表/学期树、合并学习状态、重载单门课程；已剥离 CLI 编号与终端输出。
# 文件版本: 4.0.0
"""课程与任务获取。

原型中的 M1/S1 课程编号仅用于终端输入，本模块已移除；GUI 直接使用
``term_id`` 选择课程。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import config
from .client import MoocClient, MoocError
from .models import (
    DONE,
    OVERDUE,
    PENDING,
    UPCOMING,
    Course,
    Task,
    build_course,
    build_course_without_tasks,
    extract_term_id,
)
from .session_store import load_session

STATUS_FILTERS = {
    "all": None,
    "pending": {PENDING, OVERDUE},
    "done": {DONE},
    "upcoming": {UPCOMING},
    "overdue": {OVERDUE},
}

Log = Callable[[str], None]


def _merge_course_items(
    base: list[dict[str, Any]], spoc: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """合并主客户端与 SPOC 客户端的课程条目。"""
    merged: dict[Any, dict[str, Any]] = {}
    for item in base:
        if isinstance(item, dict):
            merged[MoocClient._course_key(item)] = dict(item)
    for item in spoc:
        if not isinstance(item, dict):
            continue
        key = MoocClient._course_key(item)
        if key in merged:
            for field, value in item.items():
                if field == "_spoc" or merged[key].get(field) in (None, "", []):
                    merged[key][field] = value
        else:
            merged[key] = dict(item)
    return list(merged.values())


def load_learned_client(spoc_path: Path) -> MoocClient | None:
    """用 SPOC/学校云会话构造 learned 读取客户端。

    Args:
        spoc_path: SPOC 会话文件。

    Returns:
        客户端；会话不存在或损坏时返回 ``None``。
    """
    if not spoc_path.is_file():
        return None
    saved = load_session(spoc_path)
    if saved is None:
        return None
    try:
        return MoocClient.from_cookie_jar(saved.jar)
    except Exception:
        return None


def fetch_term(
    client: MoocClient,
    learned_client: MoocClient | None,
    term_id: int,
) -> dict[str, Any]:
    """优先用 learned 会话读取学期详情，失败时回退主会话。"""
    if learned_client is not None and learned_client is not client:
        try:
            return learned_client.get_term(term_id)
        except MoocError:
            pass
    return client.get_term(term_id)


def fetch_course_items(
    client: MoocClient,
    *,
    spoc_school_id: int | str | None = None,
    spoc_session: Path | str | None = None,
) -> list[dict[str, Any]]:
    """获取课程列表原始条目（合并 SPOC 会话）。

    Args:
        client: 主客户端。
        spoc_school_id: SPOC 学校 id 过滤。
        spoc_session: SPOC 专用会话路径。

    Returns:
        课程列表原始 JSON 条目。
    """
    spoc_path: Path = (
        Path(spoc_session) if spoc_session else config.spoc_session_file()
    )
    separate_spoc: bool = spoc_path.is_file()
    learned_client: MoocClient | None = load_learned_client(spoc_path)
    items: list[dict[str, Any]] = client.get_enrolled_courses(
        include_spoc=not separate_spoc,
        spoc_school_id=spoc_school_id,
    )
    if separate_spoc and learned_client is not None:
        try:
            items = _merge_course_items(
                items,
                learned_client.get_spoc_courses(spoc_school_id),
            )
        except MoocError:
            pass
    return items


def fetch_courses(
    client: MoocClient,
    *,
    with_tasks: bool,
    spoc_school_id: int | str | None = None,
    spoc_session: Path | str | None = None,
    progress: Callable[[int, int], None] | None = None,
    log: Log | None = None,
) -> list[Course]:
    """获取我加入的全部课程。

    Args:
        client: 主客户端。
        with_tasks: 是否逐门获取学期树。
        spoc_school_id: SPOC 学校 id 过滤。
        spoc_session: SPOC 专用会话路径。
        progress: 课程详情进度回调 ``(current, total)``。
        log: 日志回调。

    Returns:
        课程列表。
    """
    spoc_path: Path = (
        Path(spoc_session) if spoc_session else config.spoc_session_file()
    )
    learned_client: MoocClient | None = load_learned_client(spoc_path)
    items: list[dict[str, Any]] = fetch_course_items(
        client,
        spoc_school_id=spoc_school_id,
        spoc_session=spoc_path,
    )

    if not with_tasks:
        return [build_course_without_tasks(item) for item in items]

    courses: list[Course] = []
    total: int = len(items)
    for index, item in enumerate(items, 1):
        if progress is not None:
            progress(index, total)
        term_id: int | None = extract_term_id(item)
        if not term_id:
            courses.append(build_course_without_tasks(item))
            continue
        try:
            term: dict[str, Any] = fetch_term(client, learned_client, term_id)
        except MoocError as exc:
            if log:
                log("课程 %s 获取失败：%s" % (term_id, exc))
            courses.append(build_course_without_tasks(item))
            continue
        courses.append(build_course(term, item))

    courses.sort(
        key=lambda course: (
            course.end is not None and course.end < datetime.now(course.end.tzinfo),
            course.end or datetime.max.replace(tzinfo=timezone.utc),
        )
    )
    return courses


def reload_course(
    client: MoocClient,
    course: Course,
    *,
    spoc_session: Path | str | None = None,
) -> Course:
    """只重取一门课程的 term，用于完成后刷新状态。"""
    spoc_path: Path = (
        Path(spoc_session) if spoc_session else config.spoc_session_file()
    )
    learned: MoocClient | None = load_learned_client(spoc_path)
    term: dict[str, Any] = fetch_term(client, learned, course.term_id)
    fresh: Course = build_course(term)
    fresh.course_id = fresh.course_id or course.course_id
    fresh.name = fresh.name or course.name
    fresh.school = fresh.school or course.school
    fresh.school_short_name = course.school_short_name or fresh.school_short_name
    fresh.is_spoc = course.is_spoc
    fresh.start = fresh.start or course.start
    fresh.end = fresh.end or course.end
    return fresh


def task_matches(task: Task, status_value: str | None, kind: str | None) -> bool:
    """判断任务是否符合状态/类型过滤。

    Args:
        task: 任务。
        status_value: ``all/pending/done/upcoming/overdue``。
        kind: 类型关键字。

    Returns:
        符合返回 ``True``。
    """
    if status_value and status_value != "all":
        allowed = STATUS_FILTERS.get(status_value)
        if allowed is not None and task.status not in allowed:
            return False
    if kind and kind.strip():
        if kind.strip().lower() not in task.kind.lower():
            return False
    return True
