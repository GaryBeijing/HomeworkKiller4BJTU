# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-10 13:00
# 最后更新: 2026-11-16 17:20
# 文件名: quiz_page.py
# 主要用途: 测验页 Page Object：页面状态、就绪等待、题目读取、填答、主观题参考答案、成绩与提交确认。
# 文件版本: 4.6.5
"""测验页 Page Object。"""
from __future__ import annotations

import time
from typing import Any

from ..actions.base import ActionUnavailable
from ..models import Task
from .base import PageObject
from .icourse163 import close_modals, page_block_reason

__version__ = "4.6.5"
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
    "question": ".u-questionItem, .learn-assessment-question",
    "title": ".j-title .j-richTxt, .assessment-question-rich-text",
    "category": ".qaCate, .learn-assessment-question-type",
    "option_input": "input.u-tbi, .learn-assessment-option input",
    "option_text": ".u-tbl .optionCnt, .learn-assessment-option",
    "start": "a.j-startBtn",
    "agree": "#agreeCheck",
    "submit": (
        "a.j-submitBtn, button.j-submitBtn, .learn-assessment-submit button, "
        "button:has-text('提交答案')"
    ),
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
  const questionSelectors = [
    '.u-questionItem', '.learn-assessment-question',
    '[class*="questionItem"]', '[class*="question-item"]'
  ];
  let questions = 0;
  for (const selector of questionSelectors) {
    const count = [...document.querySelectorAll(selector)].filter(visible).length;
    if (count > 0) { questions = count; break; }
  }
  const clickable = [...document.querySelectorAll(
    'a,button,[role=button],.ux-btn,.u-btn'
  )].filter(visible).map(el => (el.innerText || '').trim())
    .filter(item => item && item.length <= 60);
  const startPattern = /(开始答题|开始测验|开始考试|继续答题|继续作答|继续考试)/;
  const startText = clickable.find(item => startPattern.test(item)) || '';
  const submit = document.querySelector('a.j-submitBtn') ||
    [...document.querySelectorAll('a,button,[role=button],.ux-btn,.u-btn')]
      .filter(visible).find(el => /提交答案|交卷|^提交$/.test((el.innerText || '').trim()));
  const result = document.querySelector(
    '.j-quizResult,.u-quizResult,[class*=quizResult],' +
    '[class*=QuizResult],[class*=scoreResult]'
  );
  return {
    url: location.href,
    shell: !!document.querySelector('.learn-assessment-shell, main#learn-main-content'),
    frames: document.querySelectorAll('iframe').length,
    questions,
    loginWall: /登录\s*\|\s*注册/.test(text) || text.includes('请登录后操作'),
    joinButton: [...document.querySelectorAll('a,button')].some(
      el => visible(el) && /立即参加/.test((el.innerText || '').trim())
    ),
    startVisible: !!startText,
    startText,
    buttonTexts: clickable.slice(0, 12),
    submitVisible: visible(submit),
    successText: ['提交成功', '交卷成功', '已提交', '本次得分',
                  '你的得分', '测验已完成', '考试已完成'].some(
      hit => text.includes(hit)
    ),
    resultNode: !!result && visible(result),
  };
}
"""

START_QUIZ_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
           style.display !== 'none' && style.visibility !== 'hidden';
  };
  const pattern = /(开始答题|开始测验|开始考试|继续答题|继续作答|继续考试)/;
  const nodes = [...document.querySelectorAll(
    'a,button,[role=button],.ux-btn,.u-btn'
  )].filter(visible);
  const target = nodes.find(el => pattern.test((el.innerText || '').trim()));
  if (!target) return '';
  const scope = target.closest('form') || target.parentElement?.parentElement || target.parentElement;
  const checks = scope ? [...scope.querySelectorAll('input[type=checkbox]')]
    .filter(el => visible(el) && !el.checked) : [];
  for (const checkbox of checks) {
    try { checkbox.click(); } catch (ignored) { /* 忽略不可点击的复选框 */ }
  }
  target.click();
  return (target.innerText || '').trim();
}
"""

CONFIRM_START_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
           style.display !== 'none' && style.visibility !== 'hidden';
  };
  const labels = new Set([
    '开始答题', '开始测验', '开始考试', '继续', '继续答题',
    '同意', '同意并继续', '确定'
  ]);
  const roots = [...document.querySelectorAll(
    '.ux-modal,.ant-modal,[class*=dialog],[class*=Dialog],' +
    '[class*=confirm],[class*=Confirm]'
  )].filter(visible);
  for (const root of roots) {
    const nodes = [...root.querySelectorAll('button,a,[role=button],.ux-btn,.u-btn')];
    for (const node of nodes) {
      if (visible(node) && labels.has((node.innerText || '').trim())) {
        node.click();
        return true;
      }
    }
  }
  return false;
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
() => {
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
           style.display !== 'none' && style.visibility !== 'hidden';
  };
  const selectors = [
    '.u-questionItem', '.learn-assessment-question',
    '[class*="questionItem"]', '[class*="question-item"]'
  ];
  let roots = [];
  for (const selector of selectors) {
    const nodes = [...document.querySelectorAll(selector)].filter(visible);
    if (nodes.length > 0) { roots = nodes; break; }
  }
  return roots.map((q, index) => {
    const titleEl = q.querySelector(
      '.j-title .j-richTxt, .assessment-question-rich-text, .j-richTxt, ' +
      '[class*="question-title"], [class*="questionTitle"]'
    );
    const catEl = q.querySelector(
      '.qaCate, .learn-assessment-question-type, ' +
      '[class*="question-type"], [class*="qType"]'
    );
    const inputs = [...new Set([
      ...q.querySelectorAll(
        'input.u-tbi, input[id^="op_"], .learn-assessment-option input, ' +
        'input[type=radio], input[type=checkbox]'
      )
    ])].map(inp => ({
      id: inp.id || inp.name || '', type: inp.type, checked: inp.checked
    }));
    const texts = [...q.querySelectorAll('input[type=text], textarea')].map(el => ({
      tag: el.tagName, id: el.id, value: el.value
    }));
    const labels = [...q.querySelectorAll('label.learn-assessment-option')];
    const optionTexts = (labels.length ? labels.map(label => {
      const rich = label.querySelector('.assessment-question-rich-text');
      return (rich?.innerText || label.innerText || '')
        .replace(/^\s*[A-Za-z][.、]\s*/, '').trim();
    }) : [...q.querySelectorAll(
      '.optionCnt, [class*="option-content"], [class*="optionContent"]'
    )].map(el => (el.innerText || '').trim()));
    return {
      index: index + 1,
      title: (titleEl?.innerText || '').trim(),
      category: (catEl?.innerText || '').trim(),
      inputs, texts, optionTexts,
    };
  });
}
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
        if "/announce" in url and not questions:
            return "测验页被重定向到公告页（新版任务路由未生效）"
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
        """最多等 30 秒；兼容旧 `#/learn/quiz` 与新版 `/assessments/quiz/`。"""
        self.ctx.info("等待测验页加载（最多 30 秒）…")
        deadline = time.monotonic() + QUIZ_READY_TIMEOUT_MS / 1000
        last_start_at = 0.0
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
            questions: int = int(state.get("questions") or 0)
            if questions > 0:
                return
            if (
                (state.get("successText") or state.get("resultNode"))
                and not state.get("startVisible")
                and not state.get("joinButton")
            ):
                self.screenshot(f".artifacts/quiz-submitted-{task.test_id}.png")
                raise ActionUnavailable(
                    "测验已提交或已完成，无需重复作答。"
                    f"当前 URL：{state.get('url') or page.url}"
                )
            if (
                state.get("startVisible")
                and time.monotonic() - last_start_at >= 4.0
            ):
                self.ctx.info(
                    "点击「%s」…" % (state.get("startText") or "开始答题")
                )
                if self._start_if_needed(page):
                    last_start_at = time.monotonic()
                    page.wait_for_timeout(1200)
                    continue
            page.wait_for_timeout(QUIZ_POLL_MS)

        self.screenshot(f".artifacts/quiz-noquestions-{task.test_id}.png")
        state = self._page_state(page)
        buttons = "、".join(state.get("buttonTexts") or []) or "无"
        raise ActionUnavailable(
            "测验页面 30 秒内没有加载出题目。"
            f"当前 URL：{state.get('url') or page.url}；"
            f"新版界面：{'是' if state.get('shell') else '否'}；"
            f"iframe：{int(state.get('frames') or 0)}；"
            f"可见按钮：{buttons}"
        )

    # ------------------------------------------------------------------ 开始
    def _start_if_needed(self, page) -> bool:
        """点击新版/旧版开始或继续答题入口。

        Returns:
            实际点中入口返回 ``True``。
        """
        state = self._page_state(page)
        if int(state.get("questions") or 0) > 0:
            return False
        try:
            clicked = page.evaluate(START_QUIZ_JS)
        except Exception:
            clicked = ""
        if not clicked:
            return False
        page.wait_for_timeout(600)
        try:
            page.evaluate(CONFIRM_START_JS)
        except Exception:
            pass
        page.wait_for_timeout(900)
        # 开始确认框可能被 Escape 取消，这里不再按 Escape。
        close_modals(page, press_escape=False)
        return True

    # ------------------------------------------------------------------ 填答
    def _apply(self, page, result: Any) -> None:
        fill_js = r"""
        ({qIndex, values}) => {
          const standard = [...document.querySelectorAll(
            '.u-questionItem, .learn-assessment-question'
          )];
          const roots = standard.length ? standard : [...document.querySelectorAll(
            '[class*="questionItem"],[class*="question-item"]'
          )];
          const root = roots[qIndex];
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
        page.wait_for_timeout(600)
        for plan in result.questions:
            if not plan.matched:
                continue
            if plan.question_type in ("SINGLE_CHOICE", "MULTIPLE_CHOICE", "JUDGEMENT"):
                if plan.selected_indexes:
                    # 新版 React 页面必须用真实指针事件，JS 的 input.click()
                    # 只会改变 DOM checked，不会更新组件状态，提交时 optIds 为空。
                    roots = page.locator(".learn-assessment-question")
                    handled = False
                    if roots.count() >= plan.index:
                        root = roots.nth(plan.index - 1)
                        labels = root.locator("label.learn-assessment-option")
                        clicked = 0
                        for index in plan.selected_indexes:
                            if index >= labels.count():
                                continue
                            label = labels.nth(index)
                            try:
                                # 新版选项是受控组件，点击 label 才会触发 React 状态。
                                label.click(timeout=3000)
                                page.wait_for_timeout(150)
                            except Exception:
                                continue
                            clicked += 1
                        self.ctx.log(f"  已勾选 {clicked} 项")
                        handled = True
                    if handled:
                        continue
                if plan.selected_option_ids:
                    # 旧版页面：input id 中包含 GinsMooc option id。
                    clicked = page.evaluate(
                        r"""
                        (wanted) => {
                          let count = 0;
                          const standard = [...document.querySelectorAll(
                            '.u-questionItem, .learn-assessment-question'
                          )];
                          const roots = standard.length ? standard : [...document.querySelectorAll(
                            '[class*="questionItem"],[class*="question-item"]'
                          )];
                          const inputs = roots.flatMap(root => [...root.querySelectorAll(
                            'input.u-tbi, input[id^="op_"]'
                          )]);
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
                else:
                    # 新版页面没有 option id，只能按题目内选项顺序点击。
                    clicked = page.evaluate(
                        r"""
                        ({qIndex, indexes}) => {
                          const standard = [...document.querySelectorAll(
                            '.u-questionItem, .learn-assessment-question'
                          )];
                          const roots = standard.length ? standard : [...document.querySelectorAll(
                            '[class*="questionItem"],[class*="question-item"]'
                          )];
                          const root = roots[qIndex];
                          if (!root) return 0;
                          const labels = [...root.querySelectorAll(
                            'label.learn-assessment-option'
                          )];
                          const inputs = labels.length
                            ? labels.map(label => label.querySelector('input'))
                            : [...root.querySelectorAll(
                                'input[type=radio], input[type=checkbox], input.u-tbi'
                              )];
                          let count = 0;
                          for (const index of indexes) {
                            const input = inputs[index];
                            if (!input) continue;
                            if (!input.checked) { input.click(); }
                            count++;
                          }
                          return count;
                        }
                        """,
                        {
                            "qIndex": plan.index - 1,
                            "indexes": list(plan.selected_indexes),
                        },
                    )
                self.ctx.log(f"  已勾选 {clicked} 项")
            elif plan.question_type == "COMPLETION":
                values = [blank[0] if blank else "" for blank in plan.blank_answers]
                roots = page.locator(".learn-assessment-question")
                filled = 0
                if roots.count() >= plan.index:
                    fields = roots.nth(plan.index - 1).locator(
                        "input[type=text], textarea"
                    )
                    for field_index, value in enumerate(values):
                        if field_index >= fields.count():
                            break
                        try:
                            fields.nth(field_index).fill(str(value))
                            filled += 1
                        except Exception:
                            pass
                if filled == 0:
                    filled = page.evaluate(
                        fill_js, {"qIndex": plan.index - 1, "values": values}
                    )
                self.ctx.log(f"  已填写 {filled} 个空")
            elif plan.question_type in ("HOMEWORK", "ONLINE_JUDGE"):
                self.ctx.log("  主观题已跳过（需人工作答）")
                reference = str(getattr(plan, "reference_answer", "") or "")
                if reference:
                    self.ctx.log("  参考答案：%s" % reference)

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
                      // 新版确认框没有 dialog class，使用按钮祖先文本识别。
                      const all = [...document.querySelectorAll(
                        'button, a, [role=button], .ux-btn, .u-btn'
                      )].filter(visible);
                      for (const node of all) {
                        const text = (node.innerText || '').trim();
                        if (!labels.has(text)) continue;
                        let parent = node.parentElement;
                        for (let depth = 0; parent && depth < 7; depth++) {
                          const body = parent.innerText || '';
                          if (body.includes('确认提交') || body.includes('提交后')) {
                            node.click();
                            return true;
                          }
                          parent = parent.parentElement;
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
        if "/assessments/" in url:
            return "/result" in url
        return "/learn/quiz" not in url

    def _submit(self, page, task: Task | None = None) -> bool:
        """点击提交，并等待明确的成功/成绩状态，而不是点击后立即返回。"""
        # 新版 React 页面需要一点时间把 JS 填答同步到组件状态。
        page.wait_for_timeout(600)
        button = page.locator(QUIZ_SELECTORS["submit"])
        if button.count() == 0:
            raise ActionUnavailable("没有找到「提交答案」按钮")
        try:
            button.first.click(timeout=5000)
        except Exception:
            close_modals(page)
            button.first.click(timeout=5000)

        page.wait_for_timeout(500)
        # 新版确认框可能稍晚出现，最多等待约 3 秒。
        for _ in range(6):
            if self._confirm_dialog(page):
                page.wait_for_timeout(500)
                break
            page.wait_for_timeout(500)

        deadline = time.monotonic() + QUIZ_SUBMIT_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            self.ctx.check_cancel()
            if self._submission_confirmed(page):
                return True
            page.wait_for_timeout(QUIZ_POLL_MS)
        return False

