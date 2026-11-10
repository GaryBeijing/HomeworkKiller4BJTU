# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-10 13:00
# 文件名: popup.py
# 主要用途: 视频弹题：按题库作答，未命中回退 A。
# 文件版本: 4.4.0
"""视频播放中的弹题处理。

规则：
1. 题库命中且有正确选项 → 选正确项；
2. 题库未命中 / 没有正确选项 → 选第一个选项（A）；
3. 没有选项输入框（填空等）→ 填 ``A``；
4. 最后点击“继续/确定”，让视频继续。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from hwklr.db.icourse_models import AnswerIndex
from ..pages.popup_page import CONTINUE_JS, DETECT_JS, FILL_TEXT_JS, POPUP_SELECTORS
from .quiz import parse_option_id

@dataclass(frozen=True)
class PopupChoice:
    matched: bool
    input_ids: tuple[str, ...]
    fallback_a: bool


def choose_popup_click(data: dict[str, Any] | None, index: AnswerIndex) -> PopupChoice:
    """纯逻辑：决定弹题要点击哪些选项。"""
    if not data:
        return PopupChoice(False, (), False)

    inputs = [str(item.get("id") or "") for item in (data.get("inputs") or [])]
    inputs = [item for item in inputs if item]
    question = index.find_question(
        str(data.get("title") or ""), data.get("optionTexts") or []
    )
    if question is not None:
        correct = set(question.correct_option_ids)
        matched = tuple(
            item
            for item in inputs
            if parse_option_id(item, question) in correct
        )
        if matched:
            return PopupChoice(True, matched, False)

    if inputs:
        return PopupChoice(question is not None, (inputs[0],), True)
    return PopupChoice(question is not None, (), True)


class PopupQuiz:
    def __init__(self, page: Any, index: AnswerIndex, *, settle: float = 0.3) -> None:
        self.page = page
        self.index = index
        self.settle = settle
        self.last_mode = "none"

    def detect(self) -> dict[str, Any] | None:
        try:
            return self.page.evaluate(DETECT_JS, list(POPUP_SELECTORS))
        except Exception:
            return None

    def answer(self) -> bool:
        data = self.detect()
        if not data:
            self.last_mode = "none"
            return False

        choice = choose_popup_click(data, self.index)
        clicked = 0
        for input_id in choice.input_ids:
            clicked += int(self._click_input(input_id) or 0)

        if clicked == 0 and not choice.input_ids:
            if self._fill_text("A"):
                clicked = 1
                self.last_mode = "A-text"
        elif choice.fallback_a:
            self.last_mode = "A"
        elif choice.matched:
            self.last_mode = "db"
        else:
            self.last_mode = "none"

        if clicked:
            time.sleep(self.settle)
        try:
            self.page.evaluate(CONTINUE_JS)
        except Exception:
            pass
        return clicked > 0

    def _click_input(self, input_id: str) -> bool:
        if not input_id:
            return False
        try:
            return bool(
                self.page.evaluate(
                    "(id) => { const el = document.getElementById(id); "
                    "if (!el) return false; if (!el.checked) el.click(); return true; }",
                    input_id,
                )
            )
        except Exception:
            return False

    def _fill_text(self, value: str) -> bool:
        try:
            return bool(self.page.evaluate(FILL_TEXT_JS, value))
        except Exception:
            return False
