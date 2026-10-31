# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-01 00:01
# 文件名: models.py
# 主要用途: C 程序设计功能的数据结构（课程、题目、AI 讲解、题解与判题结果）。
# 文件版本: 2.0.0
"""C 程序设计功能的数据结构。

所有对外返回的结构都提供 ``to_payload`` 方法，便于桥接层直接序列化为
JSON 传给前端。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, NamedTuple


@dataclass
class Course:
    """学生已选的一门课程。"""

    id: int
    name: str

    def to_payload(self) -> dict[str, Any]:
        """转换为前端数据。

        Returns:
            ``{"id": ..., "name": ...}``。
        """
        return {"id": self.id, "name": self.name}


@dataclass
class ProblemRef:
    """课程大纲中的一道编程题。"""

    part_name: str
    title: str
    module_id: int
    activity_id: int | None = None
    my_result: str = ""
    submit_count: int = 0
    number: int = 0

    def to_payload(self) -> dict[str, Any]:
        """转换为前端数据。

        Returns:
            题目引用字典。
        """
        return {
            "number": self.number,
            "title": self.title,
            "module_id": self.module_id,
            "activity_id": self.activity_id,
            "my_result": self.my_result,
            "submit_count": self.submit_count,
            "solved": self.my_result.startswith("AC"),
        }


@dataclass
class Part:
    """课程中的一个部分（Moodle Topic）。"""

    index: int
    name: str
    problems: list[ProblemRef] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        """转换为前端数据。

        Returns:
            部分与题目列表。
        """
        return {
            "index": self.index,
            "name": self.name,
            "problems": [problem.to_payload() for problem in self.problems],
        }


@dataclass
class CourseStructure:
    """课程结构。V2 使用本地分组，不再调用 AI 猜测结构。"""

    course_name: str
    parts: list[Part] = field(default_factory=list)
    source: str = "local"
    warning: str = ""

    def to_payload(self) -> dict[str, Any]:
        """转换为前端数据。

        Returns:
            课程名、来源、警告与部分列表。
        """
        return {
            "course_name": self.course_name,
            "source": self.source,
            "warning": self.warning,
            "parts": [part.to_payload() for part in self.parts],
        }


class TestCase(NamedTuple):
    """题目页面公开的一个测试用例。"""

    no: int
    input: str
    output: str
    time_limit: str
    memory_limit: str

    def to_payload(self) -> dict[str, Any]:
        """转换为前端数据。

        Returns:
            测试用例字典。
        """
        return {
            "no": self.no,
            "input": self.input,
            "output": self.output,
            "time_limit": self.time_limit,
            "memory_limit": self.memory_limit,
        }


class ProblemDetail(NamedTuple):
    """题目详情。"""

    title: str
    statement: str
    test_cases: tuple[TestCase, ...]
    module_id: int
    activity_id: int | None
    time_limit: str
    memory_limit: str
    raw_text: str

    def to_payload(self) -> dict[str, Any]:
        """转换为前端数据。

        Returns:
            题目详情字典。
        """
        return {
            "title": self.title,
            "statement": self.statement,
            "test_cases": [case.to_payload() for case in self.test_cases],
            "module_id": self.module_id,
            "activity_id": self.activity_id,
            "time_limit": self.time_limit,
            "memory_limit": self.memory_limit,
        }


class QuestionAnalysis(NamedTuple):
    """启发模式的结构化讲解。"""

    simplified_statement: str
    input_meaning: str
    test_data_range: str
    sample_io: str
    logic: str
    precautions: str

    def to_payload(self) -> dict[str, Any]:
        """转换为前端数据。

        Returns:
            六段式讲解字典。
        """
        return {
            "simplified_statement": self.simplified_statement,
            "input_meaning": self.input_meaning,
            "test_data_range": self.test_data_range,
            "sample_io": self.sample_io,
            "logic": self.logic,
            "precautions": self.precautions,
        }


class SolutionDraft(NamedTuple):
    """题解模式的结构化 AI 输出。"""

    solution_title: str
    explanation: str
    code: str
    notes: str

    def to_payload(self) -> dict[str, Any]:
        """转换为前端数据。

        Returns:
            题解字典。
        """
        return {
            "solution_title": self.solution_title,
            "explanation": self.explanation,
            "code": self.code,
            "notes": self.notes,
        }


class TestCaseResult(NamedTuple):
    """单个测试点的判题结果。"""

    no: int
    passed: bool
    judge_result: str
    test_input: str
    expected_output: str
    actual_output: str
    error_message: str
    time_used: str
    memory_used: str
    exit_value: str

    def to_payload(self) -> dict[str, Any]:
        """转换为前端数据。

        Returns:
            测试点结果字典。
        """
        return {
            "no": self.no,
            "passed": self.passed,
            "judge_result": self.judge_result,
            "test_input": self.test_input,
            "expected_output": self.expected_output,
            "actual_output": self.actual_output,
            "error_message": self.error_message,
            "time_used": self.time_used,
            "memory_used": self.memory_used,
            "exit_value": self.exit_value,
        }


class Consequence(NamedTuple):
    """一次提交的完整判题结果。"""

    is_ac: bool
    status: str
    current_status: str
    summary: str
    compile_message: str
    failed_cases: tuple[TestCaseResult, ...]
    all_cases: tuple[TestCaseResult, ...]
    submit_id: int | None
    raw_text: str

    def to_payload(self) -> dict[str, Any]:
        """转换为前端数据。

        Returns:
            判题结果字典。
        """
        return {
            "is_ac": self.is_ac,
            "status": self.status,
            "current_status": self.current_status,
            "summary": self.summary,
            "compile_message": self.compile_message,
            "failed_cases": [case.to_payload() for case in self.failed_cases],
            "all_cases": [case.to_payload() for case in self.all_cases],
            "submit_id": self.submit_id,
            "raw_text": self.raw_text,
        }


class IndexRow(NamedTuple):
    """编程题列表页面的一行。"""

    part_name: str
    title: str
    module_id: int
    activity_id: int | None
    my_result: str
    submit_count: int


class RecordItem(NamedTuple):
    """学习记录条目。"""

    part_name: str
    number: int
    title: str
    detail: str = ""
