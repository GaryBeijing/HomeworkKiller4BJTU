# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-16 20:30
# 最后更新: 2026-11-16 20:30
# 文件名: answer_bank.py
# 主要用途: 把已缓存课程记录整理为只读答案浏览/搜索 payload。
# 文件版本: 4.6.7
"""答案浏览与搜索。

本模块只读取 :class:`hwklr.db.icoursedb.IcourseDb` 的课程记录，不发网络
请求、不修改题库；UI 通过 ``get_answer_bank`` 动作取得结构化题目与答案。
"""
from __future__ import annotations

from typing import Any, Final

from hwklr.db.icourse_models import (
    DbQuestion,
    QuestionType,
    html_to_text,
    normalize_title,
    question_from_json,
)

__version__ = "4.6.7"
__author__ = "Gary"
__all__ = ["answer_bank_payload", "question_answer_text"]

_TYPE_LABELS: Final[dict[str, str]] = {
    QuestionType.SINGLE_CHOICE.value: "单选",
    QuestionType.MULTIPLE_CHOICE.value: "多选",
    QuestionType.JUDGEMENT.value: "判断",
    QuestionType.COMPLETION.value: "填空",
    QuestionType.HOMEWORK.value: "简答",
    QuestionType.ONLINE_JUDGE.value: "编程",
}
_LETTERS: Final[str] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_MAX_QUESTIONS: Final[int] = 1000


def _letter(index: int) -> str:
    """把选项下标转成 A/B/C… 标签。"""
    if 0 <= index < len(_LETTERS):
        return _LETTERS[index]
    return str(index + 1)


def question_answer_text(question: DbQuestion) -> str:
    """把题目答案转成适合展示的纯文本。

    Args:
        question: 题库题目。

    Returns:
        选择题返回 ``A. 选项文本`` 形式；填空/主观题返回参考答案。
    """
    if question.is_objective:
        parts: list[str] = []
        for index, option in enumerate(question.options):
            if option.answer:
                parts.append("%s. %s" % (_letter(index), option.text))
        if parts:
            return "；".join(parts)
        if question.std_answer:
            return html_to_text(question.std_answer)
    if question.type is QuestionType.COMPLETION:
        blanks = question.blanks
        if blanks:
            return "；".join(
                "第%d空：%s" % (index, " / ".join(alts))
                for index, alts in enumerate(blanks, 1)
                if alts
            )
    return question.reference_answer


def _question_payload(
    question: DbQuestion,
    *,
    test_id: int,
    test_name: str,
) -> dict[str, Any]:
    """构造单题展示 payload。"""
    return {
        "test_id": int(test_id),
        "test_name": test_name,
        "id": int(question.id),
        "type": question.type.value,
        "type_label": _TYPE_LABELS.get(question.type.value, question.type.value),
        "title": question.plain_title,
        "answer": question_answer_text(question),
        "options": [
            {
                "text": option.text,
                "answer": bool(option.answer),
            }
            for option in question.options
        ],
    }


def answer_bank_payload(
    record: dict[str, Any],
    *,
    test_id: int = 0,
    query: str = "",
) -> dict[str, Any]:
    """从课程记录生成答案浏览 payload。

    Args:
        record: :class:`IcourseDb` 的课程 payload。
        test_id: 只查看指定测验；``0`` 表示全部。
        query: 题干/答案/选项文本关键字。

    Returns:
        含 ``tests``、``questions``、``total`` 的字典。
    """
    tests_meta: Any = record.get("tests")
    entries: dict[str, Any] = (
        dict(tests_meta) if isinstance(tests_meta, dict) else {}
    )
    tests: list[dict[str, Any]] = []
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        meta: Any = entry.get("meta")
        meta = dict(meta) if isinstance(meta, dict) else {}
        try:
            current_id = int(meta.get("id", key))
        except (TypeError, ValueError):
            continue
        tests.append(
            {
                "id": current_id,
                "name": str(meta.get("name") or ("测验 %d" % current_id)),
                "question_count": int(
                    entry.get("question_count")
                    or len(entry.get("questions") or [])
                ),
                "fetched_at": float(entry.get("fetched_at") or 0.0),
                "error": str(entry.get("error") or ""),
            }
        )
    tests.sort(key=lambda item: item["id"])

    needle: str = normalize_title(query)
    questions: list[dict[str, Any]] = []
    for test in tests:
        if test_id and int(test["id"]) != int(test_id):
            continue
        entry: Any = entries.get(str(test["id"]))
        if not isinstance(entry, dict):
            continue
        for item in entry.get("questions") or []:
            if not isinstance(item, dict):
                continue
            question = question_from_json(item)
            if question is None:
                continue
            payload = _question_payload(
                question,
                test_id=test["id"],
                test_name=test["name"],
            )
            if needle:
                haystack = normalize_title(
                    " ".join(
                        [
                            payload["title"],
                            payload["answer"],
                            " ".join(option["text"] for option in payload["options"]),
                        ]
                    )
                )
                if needle not in haystack:
                    continue
            questions.append(payload)
            if len(questions) >= _MAX_QUESTIONS:
                break
        if len(questions) >= _MAX_QUESTIONS:
            break
    return {
        "tests": tests,
        "questions": questions,
        "total": len(questions),
        "test_id": int(test_id),
        "query": str(query or ""),
    }
