# -*- coding: utf-8 -*-
# 作者: Gary (Adapted from GinsMooc by gin)
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-17 15:00
# 文件名: quiz.py
# 主要用途: 测验/作业/考试任务：读取题目、本地题库匹配、实时答案兜底、填答与提交；截图受留存数据开关控制。
# 文件版本: 4.7.2
"""测验/作业：从 GinsMooc 取答案，填入页面并可选提交。

答案匹配、option id 解析与填答策略参考 GinsMooc（©2022-2024 gin），
归属说明见项目根目录 NOTICE。

默认 dry-run（只计算并展示将填的答案），只有 ``submit=True`` 才点击提交。
仅支持 MOOC，SPOC 直接拒绝。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from hwklr.db.icourse_models import (
    ALT_SEPARATOR,
    BLANK_SEPARATOR,
    AnswerIndex,
    DbQuestion,
    QuestionType,
    html_to_text,
    normalize_title,
)
from ..pages.quiz_page import QuizPage
from ..models import Course, Task
from ..pages import (
    close_modals,
    is_spoc_url,
    learn_url,
    new_assessment_url,
    new_testlist_url,
    open_route,
    page_block_reason,
)
from .base import ActionContext, ActionUnavailable, safe_screenshot

@dataclass
class QuestionPlan:
    index: int
    title: str
    matched: bool = False
    db_id: int | None = None
    reference_answer: str = ""
    question_type: str = ""
    page_option_ids: tuple[int, ...] = ()
    correct_option_ids: tuple[int, ...] = ()
    selected_option_ids: tuple[int, ...] = ()
    selected_indexes: tuple[int, ...] = ()
    blank_answers: tuple[tuple[str, ...], ...] = ()
    note: str = ""

    def is_answer_ready(self) -> bool:
        """判断该题是否有可用于填答/提交的完整答案。

        Returns:
            有可用答案返回 ``True``。
        """
        if not self.matched:
            return False
        if self.question_type in (
            "SINGLE_CHOICE",
            "MULTIPLE_CHOICE",
            "JUDGEMENT",
        ):
            return bool(self.selected_option_ids or self.selected_indexes)
        if self.question_type == "COMPLETION":
            return bool(self.blank_answers) and all(
                any(str(alt).strip() for alt in blank)
                for blank in self.blank_answers
            )
        if self.question_type in ("HOMEWORK", "ONLINE_JUDGE"):
            return bool(self.reference_answer.strip())
        return False


def ensure_plans_ready(plans: list[QuestionPlan]) -> None:
    """确认整卷所有题目都有可用答案。

    Args:
        plans: 当前测验的题目计划。

    Raises:
        ActionUnavailable: 存在未命中/无答案题目时抛出，携带题号与原因。
    """
    missing = [plan for plan in plans if not plan.is_answer_ready()]
    if not missing:
        return
    detail = "、".join(
        "第%d题%s" % (plan.index, (plan.title or "")[:20])
        for plan in missing[:5]
    )
    raise ActionUnavailable(
        "题库有 %d 道题未命中（%s），已跳过本测验且未提交。"
        % (len(missing), detail)
    )


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


def quiz_hash_path(
    kind: str,
    test_id: int,
    objective: bool | None = None,
) -> str:
    """按任务类型返回测验/作业/考试的 hash 路由。

    Args:
        kind: 任务类型。
        test_id: 测验 id。
        objective: 考试是否为客观题；``None`` 时按客观考试处理。

    Returns:
        SPA hash 路由。
    """
    tid: int = int(test_id)
    if kind == "作业":
        return f"#/learn/hw?id={tid}"
    if kind == "考试":
        if objective is False:
            return f"#/learn/examSubjective?id={tid}"
        return f"#/learn/examObject?id={tid}"
    return f"#/learn/quiz?id={tid}"


def parse_page_option_id(input_id: str) -> int | None:
    """从页面 input id 解析 GinsMooc option id。

    格式通常为 ``op_<questionId>_<optionId><13位时间戳>``。

    Args:
        input_id: 页面 input 的 id。

    Returns:
        option id；无法解析时返回 ``None``。
    """
    parts: list[str] = str(input_id or "").split("_", 2)
    if len(parts) < 3:
        return None
    tail: str = parts[2]
    if len(tail) > 13 and tail[-13:].isdigit():
        tail = tail[:-13]
    digits: str = "".join(ch for ch in tail if ch.isdigit())
    try:
        return int(digits) if digits else None
    except ValueError:
        return None


def plans_from_live_answers(
    page_questions: list[dict[str, Any]],
    answers: dict[str, Any],
) -> list[QuestionPlan]:
    """把实时答案接口结果转换为页面填写计划。

    Args:
        page_questions: ``QuizPage.read_questions()`` 的返回值。
        answers: ``GinsMoocClient.select_questions()`` 的 data。

    Returns:
        与页面题目一一对应的计划列表。
    """
    choice: set[int] = set()
    for item in answers.get("choiceAns") or []:
        try:
            choice.add(int(item))
        except (TypeError, ValueError):
            continue
    completion_raw: Any = answers.get("completionAns") or {}
    completion: dict[str, str] = {}
    if isinstance(completion_raw, dict):
        for key, value in completion_raw.items():
            if isinstance(value, dict):
                raw = value.get("stdAnswer", value.get("std_answer", ""))
            else:
                raw = value
            completion[str(key)] = html_to_text(raw)
    completion_norm: dict[str, str] = {
        normalize_title(key): value for key, value in completion.items()
    }
    homework_raw: Any = answers.get("homeworkAns") or {}
    homework: dict[str, str] = {}
    if isinstance(homework_raw, dict):
        for key, value in homework_raw.items():
            if isinstance(value, dict):
                homework[str(key)] = html_to_text(
                    value.get("answer", value.get("stdAnswer", ""))
                )
            else:
                homework[str(key)] = html_to_text(value)

    plans: list[QuestionPlan] = []
    for item in page_questions:
        index: int = int(item.get("index") or 0)
        title: str = str(item.get("title") or "")
        page_ids: list[int] = []
        for entry in item.get("inputs") or []:
            oid = parse_page_option_id(str(entry.get("id") or ""))
            if oid is not None:
                page_ids.append(oid)
        selected: tuple[int, ...] = tuple(oid for oid in page_ids if oid in choice)
        plan = QuestionPlan(index=index, title=title)
        if selected:
            plan.matched = True
            plan.question_type = (
                "SINGLE_CHOICE" if len(selected) == 1 else "MULTIPLE_CHOICE"
            )
            plan.selected_option_ids = selected
            plans.append(plan)
            continue
        std_answer: str = completion.get(title, "")
        if not std_answer:
            std_answer = completion_norm.get(normalize_title(title), "")
        if std_answer:
            plan.matched = True
            plan.question_type = QuestionType.COMPLETION.value
            plan.blank_answers = tuple(
                tuple(
                    alt.strip()
                    for alt in part.split(ALT_SEPARATOR)
                    if alt.strip()
                )
                for part in std_answer.split(BLANK_SEPARATOR)
            )
            plan.reference_answer = std_answer
            plans.append(plan)
            continue
        reference: str = homework.get(str(index - 1), "")
        if reference:
            plan.matched = True
            plan.question_type = QuestionType.HOMEWORK.value
            plan.reference_answer = reference
        plans.append(plan)
    return plans


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


TESTLIST_CLICK_JS = r"""
(name) => {
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
           style.display !== 'none' && style.visibility !== 'hidden';
  };
  const nodes = [...document.querySelectorAll('a, button, [role=button], .u-btn, .ux-btn')]
    .filter(visible)
    .map((node) => ({node, text: (node.innerText || '').trim()}))
    .filter((item) => item.text && item.text.length <= 200);
  const exact = nodes.find((item) => item.text === name);
  const partial = nodes.find((item) => item.text.includes(name));
  const target = exact || partial;
  if (!target) return '';
  target.node.click();
  return target.text;
}
"""


TESTLIST_NAV_JS = r"""
(labels) => {
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
           style.display !== 'none' && style.visibility !== 'hidden';
  };
  const wanted = new Set(labels);
  const nodes = [...document.querySelectorAll('a,button,[role=button],li,span,div')]
    .filter(visible)
    .map((node) => ({node, text: (node.innerText || '').trim()}))
    .filter((item) => item.text && item.text.length <= 20 && wanted.has(item.text));
  if (!nodes.length) return '';
  nodes[0].node.click();
  return nodes[0].text;
}
"""


TESTLIST_EXPAND_ASSESSMENT_JS = r"""
([testId, name]) => {
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
           style.display !== 'none' && style.visibility !== 'hidden';
  };
  const id = String(testId || '');
  let button = [...document.querySelectorAll(
    '[data-assessment-toggle], .learn-assessment-head'
  )].filter(visible).find((el) =>
    id && (el.getAttribute('aria-controls') || '').includes(id)
  );
  if (!button) {
    button = [...document.querySelectorAll('button, a, [role=button]')]
      .filter(visible)
      .find((el) => (el.innerText || '').includes(name));
  }
  if (!button) return {found: false, panel: ''};
  const panel = button.getAttribute('aria-controls') || '';
  if (button.getAttribute('aria-expanded') !== 'true') {
    button.click();
  }
  return {found: true, panel};
}
"""

TESTLIST_ASSESSMENT_LINK_JS = r"""
([panel, testId]) => {
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
           style.display !== 'none' && style.visibility !== 'hidden';
  };
  const id = String(testId || '');
  const root = panel ? document.getElementById(panel) : document;
  const links = [...(root || document).querySelectorAll('a')]
    .filter(visible);
  const wanted = [
    'quiz?id=' + id, 'hw?id=' + id,
    'examObject?id=' + id, 'examSubjective?id=' + id,
  ].filter((item) => !item.endsWith('='));
  const link = links.find((el) => {
    const href = el.getAttribute('href') || '';
    return wanted.some((needle) => href.includes(needle));
  }) || links.find((el) => el.classList.contains('learn-assessment-go'));
  if (!link) return '';
  const href = link.getAttribute('href') || '';
  if (!href || href.startsWith('javascript:')) return '';
  try {
    return new URL(href, location.href).href;
  } catch (error) {
    return '';
  }
}
"""


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
        hash_path = quiz_hash_path(task.kind, int(task.test_id), task.objective)
        page = self.ctx.acquire_page()
        new_url = new_assessment_url(
            course.school_short_name,
            course.course_id,
            course.term_id,
            task.kind,
            int(task.test_id),
            objective=task.objective,
        )
        new_list_url = new_testlist_url(
            course.school_short_name,
            course.course_id,
            course.term_id,
        )
        self.ctx.info(f"打开任务页：{task.name}（{task.kind}，testId={task.test_id}）")
        for attempt in range(2):
            try:
                self._open_task_page(page, base, hash_path, task, new_url, new_list_url)
                if is_spoc_url(page.url):
                    raise ActionUnavailable("测验自动化仅支持 MOOC，不支持 SPOC。")
                self._wait_ready(page, task)
                break
            except ActionUnavailable as exc:
                if attempt == 0 and "没有加载出题目" in str(exc):
                    self.ctx.warn("测验页面加载超时，使用新页面重试一次…")
                    try:
                        page.close()
                    except Exception:
                        pass
                    page = self.ctx.session.new_page()
                    self.ctx.page = page
                    continue
                raise
        page_questions = QuizPage(self.ctx, page).read_questions()
        if not page_questions:
            safe_screenshot(
                self.ctx, page, f".artifacts/quiz-noquestions-{task.test_id}.png"
            )
            raise ActionUnavailable("测验页面没有解析出任何题目。")

        self.ctx.info(f"已读取 {len(page_questions)} 道题，开始匹配题库…")
        local_error: Exception | None = None
        plans: list[QuestionPlan] = []
        try:
            index = self.ctx.repository.answer_index(
                course.term_id, task.test_id, refresh=refresh_db
            )
            plans = [self._plan_question(item, index) for item in page_questions]
        except Exception as exc:
            local_error = exc
            self.ctx.warn(f"本地题库不可用：{exc}；尝试实时答案…")

        # 本地题库缺失或部分题目未匹配时，按页面 option id/题干直接查询答案。
        if not plans or any(not plan.matched for plan in plans):
            live_plans = self._live_plans(page_questions, task.test_id)
            if (
                local_error is not None
                and live_plans
                and not any(plan.matched for plan in live_plans)
            ):
                # 本地题库异常且实时答案也没有任何命中：不要继续提交空白答案。
                live_plans = []
            if live_plans and not plans:
                plans = live_plans
                self.ctx.info("已使用实时答案。")
            elif live_plans:
                by_index = {plan.index: plan for plan in live_plans}
                replaced = 0
                for pos, plan in enumerate(plans):
                    alternative = by_index.get(plan.index)
                    if not plan.matched and alternative and alternative.matched:
                        plans[pos] = alternative
                        replaced += 1
                if replaced:
                    self.ctx.info(f"本地未匹配题目中，实时答案补全 {replaced} 题。")

        if not plans:
            if local_error is not None:
                raise ActionUnavailable(
                    "本地题库不可用，实时答案也没有返回结果：%s" % local_error
                )
            raise ActionUnavailable("题库和实时答案都没有返回可用结果")

        # 严格完整性：任意一题没有可用答案时不填、不提交，整卷跳过。
        ensure_plans_ready(plans)

        result = QuizResult(task=task, url=page.url)
        for plan in plans:
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
        result.screenshot = safe_screenshot(
            self.ctx,
            page,
            f".artifacts/quiz-{task.test_id}-{'submitted' if submit else 'dryrun'}.png",
        )
        return result

    # ------------------------------------------------------------------ 打开
    @staticmethod
    def _has_task_content(state: dict[str, Any]) -> bool:
        """判断页面是否已渲染题目、开始入口或结果页。"""
        return bool(
            int(state.get("questions") or 0) > 0
            or state.get("startVisible")
            or state.get("successText")
            or state.get("resultNode")
        )

    def _open_task_page(
        self,
        page,
        base: str,
        hash_path: str,
        task: Task,
        new_url: str = "",
        new_list_url: str = "",
    ) -> None:
        """打开任务页，兼容新版 path 路由、旧 hash 路由与评估卡片入口。"""
        if new_url:
            try:
                page.goto(new_url, wait_until="domcontentloaded", timeout=90_000)
                close_modals(page, press_escape=False)
                if self._wait_task_content(page, 30, break_on_list=True):
                    return
            except Exception as exc:
                self.ctx.warn(f"新版任务路由打开失败：{exc}")
            else:
                state = QuizPage._page_state(page)
                self.ctx.warn(
                    "新版任务路由未渲染题目：%s"
                    % (state.get("url") or page.url)
                )

        open_route(page, base, hash_path)
        close_modals(page)
        if self._wait_task_content(page, 15, break_on_list=True):
            return

        self.ctx.info("任务路由未渲染，尝试从课程评估列表打开…")
        # 考试新版没有独立详情 path，必须从 /exams 列表点击任务名与“进入考试”。
        list_url = new_url if task.kind == "考试" else new_list_url
        if self._open_from_testlist(
            page,
            base,
            task.name,
            list_url,
            task.kind,
            test_id=task.test_id,
        ):
            return
        raise ActionUnavailable(
            "无法打开%s页面（已尝试新版路由、旧版路由与课程评估列表）。"
            % task.kind
        )

    @staticmethod
    def _is_list_route(url: str) -> bool:
        """判断 URL 是否只是评估/考试列表，而不是具体任务页。"""
        text = str(url or "")
        if "/assessments" in text and "/assessments/quiz/" not in text                 and "/assessments/hw/" not in text:
            return True
        if "/exams" in text and "/exams/" not in text:
            return True
        return False

    def _wait_task_content(
        self, page, timeout_seconds: int = 30, *, break_on_list: bool = False
    ) -> bool:
        """等待题目/开始入口/结果页出现。"""
        deadline = time.monotonic() + max(1, int(timeout_seconds))
        while time.monotonic() < deadline:
            state = QuizPage._page_state(page)
            url = str(state.get("url") or getattr(page, "url", "") or "")
            # 列表页也可能出现“前往作答”文字，不能把它当成已进入测验。
            if self._is_list_route(url):
                return False
            if self._has_task_content(state):
                return True
            try:
                page.wait_for_timeout(1000)
            except Exception:
                return False
        return False

    def _open_from_testlist(
        self,
        page,
        base: str,
        name: str,
        new_list_url: str = "",
        kind: str = "",
        *,
        test_id: int | None = None,
    ) -> bool:
        """从评估列表展开卡片并打开真实“前往作答/进入考试”入口。"""
        new_learn = ""
        for marker in ("/assessments", "/exams"):
            if marker in new_list_url:
                new_learn = new_list_url.split(marker, 1)[0]
                if "?" in new_list_url:
                    new_learn += "?" + new_list_url.split("?", 1)[1]
                break
        attempts: list[str] = []
        if new_list_url:
            attempts.append(new_list_url)
        if new_learn:
            attempts.append(new_learn)
        for url in attempts:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=90_000)
                page.wait_for_timeout(1500)
            except Exception:
                continue
            if url == new_learn and kind:
                try:
                    page.evaluate(TESTLIST_NAV_JS, [kind])
                    page.wait_for_timeout(1200)
                except Exception:
                    pass
            if kind == "考试":
                if self._open_exam_entry(page, name):
                    return True
                continue
            if self._open_assessment_entry(page, name, test_id):
                return True
        # 旧版评估列表最后兜底。
        try:
            open_route(page, base, "#/learn/testlist")
            page.wait_for_timeout(1500)
        except Exception:
            return False
        if kind == "考试":
            return self._open_exam_entry(page, name)
        return self._open_assessment_entry(page, name, test_id)

    def _open_exam_entry(self, page, name: str) -> bool:
        """考试列表：先展开任务，再点“进入考试”。"""
        try:
            clicked = page.evaluate(TESTLIST_CLICK_JS, str(name))
        except Exception:
            clicked = ""
        if not clicked:
            return False
        page.wait_for_timeout(2200)
        entered = ""
        for _ in range(3):
            try:
                entered = page.evaluate(TESTLIST_CLICK_JS, "进入考试")
            except Exception:
                entered = ""
            if entered:
                break
            page.wait_for_timeout(900)
        if entered:
            page.wait_for_timeout(2500)
        close_modals(page)
        return self._wait_task_content(page, 20)

    def _open_assessment_entry(
        self, page, name: str, test_id: int | None
    ) -> bool:
        """测验/作业：展开卡片并通过 learn-assessment-go 链接进入。"""
        panel = ""
        if test_id:
            try:
                expanded = page.evaluate(
                    TESTLIST_EXPAND_ASSESSMENT_JS, [int(test_id), str(name)]
                ) or {}
                panel = str(expanded.get("panel") or "")
                page.wait_for_timeout(1200)
            except Exception:
                panel = ""
        href = ""
        if test_id:
            try:
                href = str(
                    page.evaluate(
                        TESTLIST_ASSESSMENT_LINK_JS, [panel, int(test_id)]
                    )
                    or ""
                )
            except Exception:
                href = ""
        if href:
            try:
                page.goto(href, wait_until="domcontentloaded", timeout=90_000)
                close_modals(page)
                if self._wait_task_content(page, 20):
                    return True
            except Exception as exc:
                self.ctx.warn(f"评估列表入口打开失败：{exc}")
        # 文本点击兜底：可能只是展开卡片，必须再用链接或内容确认。
        try:
            clicked = page.evaluate(TESTLIST_CLICK_JS, str(name))
        except Exception:
            clicked = ""
        if clicked:
            page.wait_for_timeout(1500)
            if test_id:
                try:
                    href = str(
                        page.evaluate(
                            TESTLIST_ASSESSMENT_LINK_JS, [panel, int(test_id)]
                        )
                        or ""
                    )
                except Exception:
                    href = ""
            if href:
                try:
                    page.goto(href, wait_until="domcontentloaded", timeout=90_000)
                    close_modals(page)
                    if self._wait_task_content(page, 20):
                        return True
                except Exception:
                    pass
            if self._wait_task_content(page, 8):
                return True
        return False

    # ------------------------------------------------------------------ 匹配
    def _live_plans(
        self,
        page_questions: list[dict[str, Any]],
        test_id: int | None,
    ) -> list[QuestionPlan]:
        """按页面 option id/填空题干实时查询答案。

        Args:
            page_questions: ``QuizPage.read_questions()`` 的返回值。
            test_id: 测验 id。

        Returns:
            实时答案计划；不可用时为空列表。
        """
        repository: Any = self.ctx.repository
        if test_id is None or repository is None:
            return []
        option_ids: list[int] = []
        titles: list[str] = []
        for item in page_questions:
            for entry in item.get("inputs") or []:
                option_id = parse_page_option_id(str(entry.get("id") or ""))
                if option_id is not None:
                    option_ids.append(option_id)
            if item.get("texts"):
                title = str(item.get("title") or "").strip()
                if title:
                    titles.append(title)
        try:
            answers: dict[str, Any] = repository.live_quiz_answers(
                int(test_id), option_ids, titles
            )
        except Exception as exc:
            self.ctx.warn(f"实时答案查询失败：{exc}")
            return []
        if not isinstance(answers, dict):
            return []
        return plans_from_live_answers(page_questions, answers)

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
        if not page_ids and option_texts:
            correct_texts = {
                normalize_title(option.text)
                for option in question.options
                if option.answer
            }
            plan.selected_indexes = tuple(
                index
                for index, text in enumerate(option_texts)
                if normalize_title(str(text)) in correct_texts
            )

        if question.type is QuestionType.COMPLETION:
            plan.blank_answers = question.blanks
            plan.reference_answer = question.reference_answer
        elif question.type in (QuestionType.HOMEWORK, QuestionType.ONLINE_JUDGE):
            plan.note = "主观题，仅展示参考答案"
            plan.reference_answer = question.reference_answer

        if (
            question.is_objective
            and not plan.selected_option_ids
            and not plan.selected_indexes
        ):
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
            if plan.reference_answer:
                self.ctx.log(f"[{plan.index}] 参考答案：{plan.reference_answer}")
        else:
            selected = plan.selected_option_ids or plan.selected_indexes
            self.ctx.log(f"[{plan.index}] 选择正确项：{selected or '无'}")

    # ------------------------------------------------------------------ 页面
    def _wait_ready(self, page, task: Task) -> None:
        QuizPage(self.ctx, page)._wait_ready(page, task)

    def _apply(self, page, result) -> None:
        QuizPage(self.ctx, page)._apply(page, result)

    def _read_score(self, page, task: Task, result) -> None:
        QuizPage(self.ctx, page)._read_score(page, task, result)

    def _submit(self, page, task: Task | None = None) -> bool:
        return QuizPage(self.ctx, page)._submit(page, task)
