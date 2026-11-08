# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-08 16:25
# 文件名: quiz.py
# 主要用途: 测验任务：读取题目、匹配题库、填答与提交。
# 文件版本: 4.0.0
"""测验/作业：从 GinsMooc 取答案，填入页面并可选提交。

默认 dry-run（只计算并展示将填的答案），只有 ``submit=True`` 才点击提交。
仅支持 MOOC，SPOC 直接拒绝。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from hwklr.db.icourse_models import AnswerIndex, DbQuestion, QuestionType
from ..models import Course, Task
from ..pages import close_modals, is_spoc_url, learn_url, open_route, page_block_reason
from .base import ActionCancelled, ActionContext

QUIZ_SELECTORS = {
    "question": ".u-questionItem",
    "title": ".j-title .j-richTxt",
    "category": ".qaCate",
    "option_input": "input.u-tbi",
    "option_text": ".u-tbl .optionCnt",
    "start": "a.j-startBtn",
    "agree": "#agreeCheck",
    "submit": "a.j-submitBtn",
}

QUIZ_READY_TIMEOUT_MS = 30_000
QUIZ_SUBMIT_TIMEOUT_MS = 20_000
QUIZ_POLL_MS = 500

QUIZ_PAGE_STATE_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
           style.display !== 'none' && style.visibility !== 'hidden';
  };
  const text = document.body?.innerText || '';
  const submit = document.querySelector('a.j-submitBtn');
  const start = document.querySelector('a.j-startBtn');
  return {
    url: location.href,
    questions: document.querySelectorAll('.u-questionItem').length,
    loginWall: /登录\s*\|\s*注册/.test(text) || text.includes('请登录后操作'),
    joinButton: [...document.querySelectorAll('a,button')].some(
      el => visible(el) && /立即参加/.test((el.innerText || '').trim())
    ),
    startVisible: visible(start),
    submitVisible: visible(submit),
    successText: ['提交成功', '交卷成功', '已提交', '本次得分',
                  '你的得分', '测验已完成', '考试已完成'].some(
      hit => text.includes(hit)
    ),
    resultNode: !!document.querySelector(
      '.j-quizResult,.u-quizResult,[class*=quizResult],' +
      '[class*=QuizResult],[class*=scoreResult]'
    ),
  };
}
"""

READ_QUESTIONS_JS = r"""
() => [...document.querySelectorAll('.u-questionItem')].map((q, index) => {
  const titleEl = q.querySelector('.j-title .j-richTxt');
  const catEl = q.querySelector('.qaCate');
  const inputs = [...q.querySelectorAll('input.u-tbi')].map(inp => ({
    id: inp.id, type: inp.type, checked: inp.checked
  }));
  const texts = [...q.querySelectorAll('input[type=text], textarea')].map(el => ({
    tag: el.tagName, id: el.id, value: el.value
  }));
  const optionTexts = [...q.querySelectorAll('.optionCnt')].map(el => (el.innerText || '').trim());
  return {
    index: index + 1,
    title: (titleEl?.innerText || '').trim(),
    category: (catEl?.innerText || '').trim(),
    inputs, texts, optionTexts,
  };
})
"""


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
            raise ActionCancelled("测验自动化仅支持 MOOC，不支持 SPOC。")
        if not course.school_short_name or not course.course_id:
            raise ActionCancelled("课程缺少 schoolShortName/courseId，无法构造测验 URL")
        if not task.test_id:
            raise ActionCancelled(f"任务「{task.name}」没有 testId")

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
            raise ActionCancelled("测验自动化仅支持 MOOC，不支持 SPOC。")

        self._wait_ready(page, task)
        page_questions = page.evaluate(READ_QUESTIONS_JS)
        if not page_questions:
            self.ctx.session.screenshot(
                page, f".artifacts/quiz-noquestions-{task.test_id}.png"
            )
            raise ActionCancelled("测验页面没有解析出任何题目。")

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
                self.ctx.info("已提交并确认成功。")
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

    # ------------------------------------------------------------------ 加载/登录
    @staticmethod
    def _page_state(page) -> dict[str, Any]:
        try:
            return page.evaluate(QUIZ_PAGE_STATE_JS) or {}
        except Exception:
            return {}

    @staticmethod
    def _blocked_reason(state: dict[str, Any]) -> str:
        url = str(state.get("url") or "")
        questions = int(state.get("questions") or 0)
        if "/course/" in url and "/learn/" not in url:
            return "测验页被重定向到课程介绍页（登录态失效或未选课）"
        if state.get("loginWall") and not questions:
            return "测验页要求登录（登录态已失效）"
        if (
            state.get("joinButton")
            and not questions
            and not state.get("startVisible")
        ):
            return "测验页显示「立即参加」，可能未选课或登录态失效"
        return ""

    def _wait_ready(self, page, task: Task) -> None:
        """最多等 30 秒；一旦发现重定向/登录墙立即给出明确错误。"""
        self.ctx.info("等待测验页加载（最多 30 秒）…")
        deadline = time.monotonic() + QUIZ_READY_TIMEOUT_MS / 1000
        started = False
        while time.monotonic() < deadline:
            self.ctx.check_cancel()
            blocked = page_block_reason(page)
            if blocked:
                self.ctx.session.screenshot(
                    page, f".artifacts/quiz-blocked-{task.test_id}.png"
                )
                raise ActionCancelled(f"{blocked}。当前 URL：{page.url}")
            state = self._page_state(page)
            reason = self._blocked_reason(state)
            if reason:
                self.ctx.session.screenshot(
                    page, f".artifacts/quiz-blocked-{task.test_id}.png"
                )
                raise ActionCancelled(
                    f"{reason}。当前 URL：{state.get('url') or page.url}"
                )
            if int(state.get("questions") or 0) > 0:
                return
            if not started and state.get("startVisible"):
                self.ctx.info("点击「开始测验」…")
                self._start_if_needed(page)
                started = True
            page.wait_for_timeout(QUIZ_POLL_MS)

        self.ctx.session.screenshot(
            page, f".artifacts/quiz-noquestions-{task.test_id}.png"
        )
        state = self._page_state(page)
        raise ActionCancelled(
            "测验页面 30 秒内没有加载出题目（可能需要手动处理验证码/协议）。"
            f"当前 URL：{state.get('url') or page.url}"
        )

    # ------------------------------------------------------------------ 开始
    def _start_if_needed(self, page) -> None:
        if page.locator(QUIZ_SELECTORS["question"]).count() > 0:
            return
        start = page.locator(QUIZ_SELECTORS["start"])
        if start.count() == 0 or not start.first.is_visible():
            return
        agree = page.locator(QUIZ_SELECTORS["agree"])
        if agree.count():
            try:
                agree.check()
            except Exception:
                agree.click()
        start.first.click()
        page.wait_for_timeout(1500)
        close_modals(page)

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

    # ------------------------------------------------------------------ 填答
    def _apply(self, page, result: QuizResult) -> None:
        fill_js = r"""
        ({qIndex, values}) => {
          const root = document.querySelectorAll('.u-questionItem')[qIndex];
          if (!root) return 0;
          const fields = [...root.querySelectorAll('input[type=text], textarea')];
          let count = 0;
          for (let i = 0; i < Math.min(fields.length, values.length); i++) {
            const el = fields[i];
            const setter = Object.getOwnPropertyDescriptor(
              el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,
              'value').set;
            setter.call(el, values[i]);
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
            count++;
          }
          return count;
        }
        """
        for plan in result.questions:
            if not plan.matched:
                continue
            if plan.question_type in ("SINGLE_CHOICE", "MULTIPLE_CHOICE", "JUDGEMENT"):
                # 页面 input 的完整 id 需要从 DOM 找：用选项前缀匹配
                clicked = page.evaluate(
                    r"""
                    (wanted) => {
                      let count = 0;
                      const inputs = [...document.querySelectorAll('.u-questionItem input.u-tbi')];
                      for (const inp of inputs) {
                        const raw = (inp.id || '').split('_').slice(2).join('_');
                        for (const oid of wanted) {
                          if (raw.startsWith(String(oid)) && raw.slice(String(oid).length).match(/^\d+$/)) {
                            if (!inp.checked) { inp.click(); }
                            count++;
                            break;
                          }
                        }
                      }
                      return count;
                    }
                    """,
                    list(plan.selected_option_ids),
                )
                self.ctx.log(f"  已勾选 {clicked} 项")
            elif plan.question_type == "COMPLETION":
                values = [blank[0] if blank else "" for blank in plan.blank_answers]
                filled = page.evaluate(
                    fill_js, {"qIndex": plan.index - 1, "values": values}
                )
                self.ctx.log(f"  已填写 {filled} 个空")
            elif plan.question_type in ("HOMEWORK", "ONLINE_JUDGE"):
                self.ctx.log("  主观题已跳过（需人工作答）")

    # ------------------------------------------------------------------ 提交
    def _confirm_dialog(self, page) -> bool:
        """只在可见的确认弹窗里点确定/提交，避免误点页面其它按钮。"""
        try:
            return bool(
                page.evaluate(
                    r"""
                    () => {
                      const visible = (el) => {
                        if (!el) return false;
                        const rect = el.getBoundingClientRect();
                        const style = getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 &&
                               style.display !== 'none' &&
                               style.visibility !== 'hidden';
                      };
                      const labels = new Set(['确定', '确认', '提交', '是', '继续']);
                      const roots = [...document.querySelectorAll(
                        '.ux-modal, .ant-modal, [class*=dialog], [class*=Dialog], ' +
                        '[class*=confirm], [class*=Confirm]'
                      )].filter(visible);
                      for (const root of roots) {
                        const nodes = [...root.querySelectorAll(
                          'button, a, [role=button], .ux-btn, .u-btn'
                        )];
                        for (const node of nodes) {
                          const text = (node.innerText || '').trim();
                          if (labels.has(text) && visible(node)) {
                            node.click();
                            return true;
                          }
                        }
                      }
                      return false;
                    }
                    """
                )
            )
        except Exception:
            return False

    def _submission_confirmed(self, page) -> bool:
        state = self._page_state(page)
        if state.get("successText") or state.get("resultNode"):
            return True
        url = str(state.get("url") or "")
        # 被踢回登录页/课程介绍页不能算提交成功。
        if "/member/login" in url or (
            "/course/" in url and "/learn/" not in url
        ):
            return False
        if not state.get("submitVisible") and int(state.get("questions") or 0) == 0:
            return True
        return "/learn/quiz" not in url

    def _submit(self, page, task: Task | None = None) -> bool:
        """点击提交，并等待明确的成功/成绩状态，而不是点击后立即返回。"""
        button = page.locator(QUIZ_SELECTORS["submit"])
        if button.count() == 0:
            raise ActionCancelled("没有找到「提交答案」按钮")
        try:
            button.first.click(timeout=5000)
        except Exception:
            close_modals(page)
            button.first.click(timeout=5000)

        page.wait_for_timeout(800)
        if self._confirm_dialog(page):
            page.wait_for_timeout(800)

        deadline = time.monotonic() + QUIZ_SUBMIT_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            self.ctx.check_cancel()
            if self._submission_confirmed(page):
                return True
            page.wait_for_timeout(QUIZ_POLL_MS)
        return False
