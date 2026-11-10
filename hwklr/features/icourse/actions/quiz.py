# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-10 13:00
# 文件名: quiz.py
# 主要用途: 测验任务：读取题目、匹配题库、填答与提交。
# 文件版本: 4.4.0
"""测验/作业：从 GinsMooc 取答案，填入页面并可选提交。

默认 dry-run（只计算并展示将填的答案），只有 ``submit=True`` 才点击提交。
仅支持 MOOC，SPOC 直接拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hwklr.db.icourse_models import AnswerIndex, DbQuestion, QuestionType
from ..pages.quiz_page import QuizPage
from ..models import Course, Task
from ..pages import close_modals, is_spoc_url, learn_url, open_route, page_block_reason
from .base import ActionContext, ActionUnavailable

@dataclass
class QuestionPlan:
    index: int
    title: str
    matched: bool = False
    db_id: int | None = None
    question_type: str = ""
    page_option_ids: tuple[int, ...] = ()
    correct_option_ids: tuple[int, ...] = ()
    selected_option_ids: tuple[int, ...] = ()
    blank_answers: tuple[tuple[str, ...], ...] = ()
    note: str = ""


@dataclass
class QuizResult:
    task: Task
    url: str
    questions: list[QuestionPlan] = field(default_factory=list)
    applied: bool = False
    submitted: bool = False
    screenshot: str = ""
    score: float | None = None
    total_score: float | None = None
    score_text: str = ""
    full_score: bool | None = None

    @property
    def matched(self) -> int:
        return sum(1 for question in self.questions if question.matched)


def parse_option_id(input_id: str, question: DbQuestion) -> int | None:
    """从 ``op_<qid>_<optionId><timestamp>`` 中匹配出题库 option id。"""
    parts = str(input_id or "").split("_", 2)
    if len(parts) < 3:
        return None
    raw = parts[2]
    for option in question.options:
        prefix = str(option.id)
        if raw.startswith(prefix) and raw[len(prefix):].isdigit():
            return option.id
    return None


class QuizAction:
    def __init__(self, ctx: ActionContext) -> None:
        self.ctx = ctx

    def run(
        self,
        course: Course,
        task: Task,
        *,
        submit: bool = False,
        apply: bool = True,
        refresh_db: bool = False,
        silent: bool = False,
    ) -> QuizResult:
        self.ctx.check_cancel()
        if course.is_spoc:
            raise ActionUnavailable("测验自动化仅支持 MOOC，不支持 SPOC。")
        if not course.school_short_name or not course.course_id:
            raise ActionUnavailable("课程缺少 schoolShortName/courseId，无法构造测验 URL")
        if not task.test_id:
            raise ActionUnavailable(f"任务「{task.name}」没有 testId")

        base = learn_url(
            course.school_short_name,
            course.course_id,
            course.term_id,
            spoc=course.is_spoc,
        )
        hash_path = f"#/learn/quiz?id={int(task.test_id)}"
        url = base + hash_path
        page = self.ctx.acquire_page()
        self.ctx.info(f"打开测验页：{task.name}（testId={task.test_id}）")
        open_route(page, base, hash_path)
        close_modals(page)

        if is_spoc_url(page.url):
            raise ActionUnavailable("测验自动化仅支持 MOOC，不支持 SPOC。")

        self._wait_ready(page, task)
        page_questions = QuizPage(self.ctx, page).read_questions()
        if not page_questions:
            self.ctx.session.screenshot(
                page, f".artifacts/quiz-noquestions-{task.test_id}.png"
            )
            raise ActionUnavailable("测验页面没有解析出任何题目。")

        self.ctx.info(f"已读取 {len(page_questions)} 道题，开始匹配题库…")
        index = self.ctx.repository.answer_index(
            course.term_id, task.test_id, refresh=refresh_db
        )
        result = QuizResult(task=task, url=page.url)

        for item in page_questions:
            plan = self._plan_question(item, index)
            result.questions.append(plan)
            self._log_plan(plan)
        self.ctx.info(f"题库匹配：{result.matched}/{len(result.questions)} 题。")

        if apply:
            self.ctx.info("开始填答…")
            self._apply(page, result)
            result.applied = True

        if submit:
            self.ctx.info("提交答案并等待成功状态…")
            result.submitted = self._submit(page, task)
            if result.submitted:
                self._read_score(page, task, result)
                self.ctx.info(
                    "已提交并确认成功"
                    + ("，得分 %s" % result.score_text if result.score_text else "。")
                )
            else:
                self.ctx.warn(
                    "已点击提交，但 20 秒内未检测到明确的成功/成绩状态；"
                    "请打开页面确认是否真的提交成功。"
                )
        else:
            self.ctx.info("已填写答案，未提交。可在设置中开启自动提交测验。")

        # 提交后站点常弹「并发限制」提示，截图前先关掉，保留真实成绩页。
        close_modals(page)
        self.ctx.info("保存截图…")
        shot = self.ctx.session.screenshot(
            page, f".artifacts/quiz-{task.test_id}-{'submitted' if submit else 'dryrun'}.png"
        )
        result.screenshot = str(shot)
        return result

    # ------------------------------------------------------------------ 匹配
    def _plan_question(
        self, item: dict[str, Any], index: AnswerIndex
    ) -> QuestionPlan:
        title = str(item.get("title") or "")
        option_texts = item.get("optionTexts") or []
        plan = QuestionPlan(index=int(item.get("index") or 0), title=title)

        question = index.find_question(title, option_texts)
        if question is None:
            plan.note = "题库中没有匹配到该题"
            return plan

        plan.matched = True
        plan.db_id = question.id
        plan.question_type = question.type.value
        page_ids: list[int] = []
        for entry in item.get("inputs") or []:
            oid = parse_option_id(entry.get("id", ""), question)
            if oid is not None:
                page_ids.append(oid)
        plan.page_option_ids = tuple(page_ids)
        correct = set(question.correct_option_ids)
        plan.selected_option_ids = tuple(oid for oid in page_ids if oid in correct)

        if question.type is QuestionType.COMPLETION:
            plan.blank_answers = question.blanks
        elif question.type in (QuestionType.HOMEWORK, QuestionType.ONLINE_JUDGE):
            plan.note = "主观题，仅展示参考答案"

        if question.is_objective and not plan.selected_option_ids:
            plan.note = "题库答案与页面选项对不上"
        return plan

    def _log_plan(self, plan: QuestionPlan) -> None:
        if not plan.matched:
            self.ctx.warn(f"[{plan.index}] 未匹配：{plan.title[:50]}")
            return
        if plan.question_type == "COMPLETION":
            answers = " / ".join(" | ".join(blank) for blank in plan.blank_answers)
            self.ctx.log(f"[{plan.index}] 填空：{answers}")
        elif plan.question_type in ("HOMEWORK", "ONLINE_JUDGE"):
            self.ctx.log(f"[{plan.index}] 主观题（仅展示）")
        else:
            self.ctx.log(
                f"[{plan.index}] 选择正确项：{plan.selected_option_ids or '无'}"
            )

    # ------------------------------------------------------------------ 页面
    def _wait_ready(self, page, task: Task) -> None:
        QuizPage(self.ctx, page)._wait_ready(page, task)

    def _apply(self, page, result) -> None:
        QuizPage(self.ctx, page)._apply(page, result)

    def _read_score(self, page, task: Task, result) -> None:
        QuizPage(self.ctx, page)._read_score(page, task, result)

    def _submit(self, page, task: Task | None = None) -> bool:
        return QuizPage(self.ctx, page)._submit(page, task)
