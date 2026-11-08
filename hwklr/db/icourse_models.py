# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: icourse_models.py
# 主要用途: GinsMooc 题库纯数据模型、题目归一化与答案索引。
# 文件版本: 4.0.0
"""GinsMooc 数据模型与答案归一化。

这一层只做纯数据转换，不做 IO，方便单元测试。
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

BLANK_SEPARATOR = "##%_YZPRLFH_%##"
ALT_SEPARATOR = " / "


class QuestionType(str, Enum):
    SINGLE_CHOICE = "SINGLE_CHOICE"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    JUDGEMENT = "JUDGEMENT"
    COMPLETION = "COMPLETION"
    HOMEWORK = "HOMEWORK"
    ONLINE_JUDGE = "ONLINE_JUDGE"

    @classmethod
    def parse(cls, value: Any) -> "QuestionType | None":
        try:
            return cls(str(value))
        except (ValueError, TypeError):
            return None


_HTML_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\ufeff]")


def html_to_text(value: Any) -> str:
    """把题库里的 HTML 片段转成可读纯文本。"""
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = _HTML_TAG.sub(" ", text)
    text = html.unescape(text)
    text = _ZERO_WIDTH.sub("", text)
    return _SPACE.sub(" ", text).strip()


def normalize_title(value: str) -> str:
    """用于标题匹配：去 HTML、零宽字符、空白归一、大小写归一。"""
    return _SPACE.sub(" ", html_to_text(value)).strip().lower()


@dataclass(frozen=True)
class Option:
    id: int
    content: str
    answer: bool = False

    @property
    def text(self) -> str:
        return html_to_text(self.content)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "content": self.content, "answer": self.answer}


@dataclass(frozen=True)
class DbQuestion:
    id: int
    type: QuestionType
    title: str
    std_answer: str | None = None
    options: tuple[Option, ...] = ()
    answer: str | None = None
    description: str | None = None
    memory_limit: int | None = None
    time_limit: int | None = None

    @property
    def plain_title(self) -> str:
        return html_to_text(self.title)

    @property
    def correct_option_ids(self) -> tuple[int, ...]:
        return tuple(option.id for option in self.options if option.answer)

    @property
    def blanks(self) -> tuple[tuple[str, ...], ...]:
        """填空题：每个空一个元组，元组内是该空的备选答案。"""
        if not self.std_answer:
            return ()
        parts = [part.strip() for part in self.std_answer.split(BLANK_SEPARATOR)]
        return tuple(
            tuple(alt.strip() for alt in part.split(ALT_SEPARATOR) if alt.strip())
            for part in parts
        )

    @property
    def reference_answer(self) -> str:
        return html_to_text(self.std_answer or self.answer or "")

    @property
    def is_objective(self) -> bool:
        return self.type in (
            QuestionType.SINGLE_CHOICE,
            QuestionType.MULTIPLE_CHOICE,
            QuestionType.JUDGEMENT,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "title": self.title,
            "std_answer": self.std_answer,
            "options": [option.to_dict() for option in self.options],
            "answer": self.answer,
            "description": self.description,
            "memory_limit": self.memory_limit,
            "time_limit": self.time_limit,
        }

    def to_cache_dict(self) -> dict[str, Any]:
        """与 API 字段一致的缓存格式，保证 question_from_json 可回读。"""
        return {
            "id": self.id,
            "type": self.type.value,
            "title": self.title,
            "stdAnswer": self.std_answer,
            "optionList": [option.to_dict() for option in self.options],
            "answer": self.answer,
            "description": self.description,
            "memoryLimit": self.memory_limit,
            "timeLimit": self.time_limit,
        }


@dataclass(frozen=True)
class DbTest:
    id: int
    name: str
    objective: bool = True
    release_time: str = ""
    deadline: str = ""
    chapter_id: int | None = None
    chapter_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "objective": self.objective,
            "release_time": self.release_time,
            "deadline": self.deadline,
            "chapter_id": self.chapter_id,
            "chapter_name": self.chapter_name,
        }

    def to_cache_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "objective": self.objective,
            "releaseTime": self.release_time,
            "deadline": self.deadline,
            "chapterId": self.chapter_id,
            "chapterName": self.chapter_name,
        }


@dataclass(frozen=True)
class DbCourse:
    id: int
    name: str
    school: str = ""
    image_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "school": self.school,
            "image_url": self.image_url,
        }

    def to_cache_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "school": self.school,
            "imageUrl": self.image_url,
        }


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool:
    return bool(value)


def option_from_json(data: dict[str, Any]) -> Option | None:
    oid = _int_or_none(data.get("id"))
    if oid is None:
        return None
    return Option(
        id=oid,
        content=str(data.get("content") or ""),
        answer=_bool(data.get("answer")),
    )


def question_from_json(data: dict[str, Any]) -> DbQuestion | None:
    qid = _int_or_none(data.get("id"))
    qtype = QuestionType.parse(data.get("type"))
    if qid is None or qtype is None:
        return None
    option_items = data.get("optionList")
    if option_items is None:
        option_items = data.get("options") or []
    options = tuple(
        option
        for option in (
            option_from_json(item)
            for item in (option_items or [])
            if isinstance(item, dict)
        )
        if option is not None
    )
    return DbQuestion(
        id=qid,
        type=qtype,
        title=str(data.get("title") or ""),
        std_answer=data.get("stdAnswer", data.get("std_answer")),
        options=options,
        answer=data.get("answer"),
        description=data.get("description"),
        memory_limit=_int_or_none(data.get("memoryLimit", data.get("memory_limit"))),
        time_limit=_int_or_none(data.get("timeLimit", data.get("time_limit"))),
    )


def test_from_json(data: dict[str, Any]) -> DbTest | None:
    tid = _int_or_none(data.get("id"))
    if tid is None:
        return None
    return DbTest(
        id=tid,
        name=str(data.get("name") or ""),
        objective=bool(data.get("objective", True)),
        release_time=str(data.get("releaseTime", data.get("release_time")) or ""),
        deadline=str(data.get("deadline") or ""),
        chapter_id=_int_or_none(data.get("chapterId", data.get("chapter_id"))),
        chapter_name=str(data.get("chapterName", data.get("chapter_name")) or ""),
    )


def course_from_json(data: dict[str, Any]) -> DbCourse | None:
    cid = _int_or_none(data.get("id"))
    if cid is None:
        return None
    return DbCourse(
        id=cid,
        name=str(data.get("name") or ""),
        school=str(data.get("school") or ""),
        image_url=str(data.get("imageUrl", data.get("image_url")) or ""),
    )


@dataclass
class AnswerIndex:
    """按选项 ID / 题干快速查答案。"""

    questions: tuple[DbQuestion, ...] = ()
    by_option_id: dict[int, tuple[DbQuestion, Option]] = field(default_factory=dict)
    by_title: dict[str, DbQuestion] = field(default_factory=dict)

    @classmethod
    def from_questions(cls, questions: Iterable[DbQuestion]) -> "AnswerIndex":
        items = tuple(questions)
        by_option: dict[int, tuple[DbQuestion, Option]] = {}
        by_title: dict[str, DbQuestion] = {}
        for question in items:
            for option in question.options:
                by_option[option.id] = (question, option)
            key = normalize_title(question.title)
            if key:
                by_title.setdefault(key, question)
        return cls(questions=items, by_option_id=by_option, by_title=by_title)

    def correct_for_option_ids(self, option_ids: Iterable[int]) -> list[int]:
        """给定页面上的 oid 列表，返回其中属于正确答案的 oid（保持输入顺序）。"""
        out: list[int] = []
        for oid in option_ids:
            found = self.by_option_id.get(int(oid))
            if found and found[1].answer:
                out.append(int(oid))
        return out

    def find(self, title: str) -> DbQuestion | None:
        return self.by_title.get(normalize_title(title))

    def find_by_options(self, option_texts: Iterable[str]) -> DbQuestion | None:
        """题干匹配失败时，用选项文本重合度兜底。"""
        wanted = {
            normalize_title(text)
            for text in option_texts
            if normalize_title(text)
        }
        if not wanted:
            return None
        best: DbQuestion | None = None
        best_score = 0
        for question in self.questions:
            texts = {normalize_title(option.text) for option in question.options}
            score = len(wanted & texts)
            if score > best_score:
                best, best_score = question, score
        return best if best_score else None

    def find_question(
        self, title: str, option_texts: Iterable[str] = ()
    ) -> DbQuestion | None:
        return self.find(title) or self.find_by_options(option_texts)

    def option_text(self, option_id: int) -> str:
        found = self.by_option_id.get(int(option_id))
        return found[1].text if found else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "questions": [question.to_dict() for question in self.questions],
        }
