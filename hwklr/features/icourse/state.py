# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-10 12:30
# 文件名: state.py
# 主要用途: icourse 课程/选择/任务树的单一状态容器，避免 Feature 内多份缓存不同步。
# 文件版本: 4.4.0
"""icourse 课程状态容器。"""
from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from typing import Any

from .models import Course

__version__ = "4.4.0"
__author__ = "Gary"
__all__ = ["CourseState"]


@dataclass
class CourseState:
    """当前账号、课程列表与已选课程的唯一内存状态。"""

    member: dict[str, Any] = field(default_factory=dict)
    course_items: list[dict[str, Any]] = field(default_factory=list)
    courses: list[Course] = field(default_factory=list)
    selected: Course | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    catalog_ids: set[int] | None = None
    version: int = 0
    lock: threading.RLock = field(
        default_factory=threading.RLock, repr=False, compare=False
    )

    def replace_courses(
        self,
        items: list[dict[str, Any]],
        courses: list[Course],
        member: dict[str, Any],
    ) -> None:
        """替换课程列表与当前账号，不清除已选课程。"""
        self.course_items = list(items)
        self.courses = list(courses)
        self.member = dict(member)
        self.version += 1

    def select(
        self, course: Course, payload: dict[str, Any], member: dict[str, Any]
    ) -> None:
        """记录已选课程并同步列表摘要。"""
        self.selected = course
        self.payload = copy.deepcopy(payload)
        self.member = dict(member)
        self._sync_summary(course)
        self.version += 1

    def apply_completion(self, course: Course, payload: dict[str, Any]) -> None:
        """任务结束后用刷新过的课程替换已选课程与列表摘要。"""
        self.selected = course
        self.payload = copy.deepcopy(payload)
        self._sync_summary(course)
        self.version += 1

    def _sync_summary(self, course: Course) -> None:
        for index, existing in enumerate(self.courses):
            if existing.term_id == course.term_id:
                self.courses[index] = course
                return
        self.courses.append(course)

    def clear(self, *, clear_catalog: bool = False) -> None:
        """清空账号与课程状态。"""
        self.member = {}
        self.course_items = []
        self.courses = []
        self.selected = None
        self.payload = {}
        if clear_catalog:
            self.catalog_ids = None
        self.version += 1
