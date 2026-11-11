# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-10 13:00
# 最后更新: 2026-11-11 10:00
# 文件名: quiz_page.py
# 主要用途: 测验页 Page Object：页面状态、就绪等待、题目读取、填答、成绩与提交确认；截图受留存数据开关控制。
# 文件版本: 4.4.3
"""测验页 Page Object。"""
from __future__ import annotations

import time
from typing import Any

from ..actions.base import ActionUnavailable
from ..models import Task
from .base import PageObject
from .icourse163 import close_modals, page_block_reason

__version__ = "4.4.3"
__author__ = "Gary"
__all__ = ["QUIZ_SELECTORS", "QuizPage", "READ_QUESTIONS_JS"]


def _to_float(value: Any) -> float | None:
    """把成绩文本转换为浮点数。"""
    try:
        text = str(value or "").strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


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

SCORE_READ_JS = r"""
() => {
  const text = document.body?.innerText || '';
  const pick = (patterns) => {
    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (match) return match[1];
    }
    return '';
  };
  const score = pick([
    /本次得分\s*[:：]?\s*([\d.]+)/,
    /你的得分\s*[:：]?\s*([\d.]+)/,
    /得分\s*[:：]?\s*([\d.]+)/,
  ]);
  const total = pick([
    /满分\s*[:：]?\s*([\d.]+)/,
    /总分\s*[:：]?\s*([\d.]+)/,
    /共\s*([\d.]+)\s*分/,
  ]);
  let pairScore = '';
  let pairTotal = '';
  const pair = text.match(/([\d.]+)\s*[\/／]\s*([\d.]+)\s*分?/);
  if (pair) {
    pairScore = pair[1];
    pairTotal = pair[2];
  }
  return {score, total, pairScore, pairTotal};
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


class QuizPage(PageObject):
    """测验页。"""

    def read_questions(self) -> list[dict[str, Any]]:
        assert self.page is not None
        return self.page.evaluate(READ_QUESTIONS_JS) or []

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
                self.screenshot(f".artifacts/quiz-blocked-{task.test_id}.png")
                raise ActionUnavailable(f"{blocked}。当前 URL：{page.url}")
            state = self._page_state(page)
            reason = self._blocked_reason(state)
            if reason:
                self.screenshot(f".artifacts/quiz-blocked-{task.test_id}.png")
                raise ActionUnavailable(
                    f"{reason}。当前 URL：{state.get('url') or page.url}"
                )
            if int(state.get("questions") or 0) > 0:
                return
            if not started and state.get("startVisible"):
                self.ctx.info("点击「开始测验」…")
                self._start_if_needed(page)
                started = True
            page.wait_for_timeout(QUIZ_POLL_MS)

        self.screenshot(f".artifacts/quiz-noquestions-{task.test_id}.png")
        state = self._page_state(page)
        raise ActionUnavailable(
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

    # ------------------------------------------------------------------ 填答
    def _apply(self, page, result: Any) -> None:
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

    # ------------------------------------------------------------------ 成绩
    def _read_score(self, page, task: Task, result: Any) -> None:
        """提交后读取成绩与满分；读不到时保留空值。

        Args:
            page: 测验结果页。
            task: 任务（可能带 ``total_score``）。
            result: 待填充的测验结果。
        """
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            try:
                data: Any = page.evaluate(SCORE_READ_JS)
            except Exception:
                data = {}
            score = _to_float((data or {}).get("score"))
            if score is None:
                score = _to_float((data or {}).get("pairScore"))
            total = _to_float((data or {}).get("total"))
            if total is None:
                total = _to_float((data or {}).get("pairTotal"))
            if score is not None:
                result.score = score
                result.total_score = total
                break
            page.wait_for_timeout(400)
        if result.total_score is None and task.total_score is not None:
            result.total_score = float(task.total_score)
        if result.score is None:
            return
        if result.total_score is not None:
            result.full_score = result.score >= result.total_score - 0.01
            result.score_text = "%g/%g" % (result.score, result.total_score)
        else:
            result.score_text = "%g 分" % result.score

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
            raise ActionUnavailable("没有找到「提交答案」按钮")
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

