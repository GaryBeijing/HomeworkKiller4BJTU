# -*- coding: utf-8 -*-
# 作者: Gary (Adapted from GinsMooc by gin)
# 编写日期: 2026-11-17 10:00
# 最后更新: 2026-11-17 10:00
# 文件名: review_page.py
# 主要用途: 作业互评页 Page Object：入口识别、满分选项、评语填写、提交/下一份与状态诊断。
# 文件版本: 4.7.0
"""作业互评页 Page Object。

互评流程参考 GinsMooc 扩展（©2022-2024 gin）；当前实现同时兼容旧版
``.u-questionItem.u-analysisQuestion`` 与新版 React 互评页的常见结构。
"""
from __future__ import annotations

from typing import Any

from .base import PageObject

__version__ = "4.7.0"
__author__ = "Gary (Adapted from GinsMooc by gin)"
__all__ = [
    "REVIEW_ENTRY_TEXTS",
    "REVIEW_PAGE_STATE_JS",
    "REVIEW_SELECTORS",
    "ReviewPage",
]

REVIEW_ENTRY_TEXTS: tuple[str, ...] = (
    "前往互评",
    "开始互评",
    "去互评",
    "互评",
    "评价作业",
)
REVIEW_SELECTORS: dict[str, str] = {
    "review_item": (
        ".u-questionItem.u-analysisQuestion.analysisMode, "
        ".u-questionItem.u-analysisQuestion, .u-analysisQuestion"
    ),
    "score_group": ".s",
    "comment": "textarea, [contenteditable='true']",
    "submit": (
        ".u-homework-evaAction .bottombtnwrap .j-submitbtn, "
        "button:has-text('提交互评'), button:has-text('提交评价')"
    ),
    "result": ".u-homework-evaAction .xlinfo",
    "next": ".u-homework-evaAction .xlinfo .j-gotonext",
}

REVIEW_PAGE_STATE_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
           style.display !== 'none' && style.visibility !== 'hidden';
  };
  const text = document.body?.innerText || '';
  const items = [...document.querySelectorAll(
    '.u-questionItem.u-analysisQuestion.analysisMode, ' +
    '.u-questionItem.u-analysisQuestion, .u-analysisQuestion, ' +
    '[class*="peerReview"] [class*="question"], [class*="PeerReview"] [class*="question"]'
  )].filter(visible);
  const clickable = [...document.querySelectorAll('a,button,[role=button]')]
    .filter(visible).map((el) => (el.innerText || '').trim())
    .filter((item) => item && item.length <= 30);
  const noPending = ['暂无可互评', '互评已完成', '没有待互评', '互评已结束']
    .some((needle) => text.includes(needle));
  return {
    url: location.href,
    reviewMode: items.length > 0,
    items: items.length,
    submitVisible: visible(document.querySelector(
      '.u-homework-evaAction .bottombtnwrap .j-submitbtn'
    )),
    nextVisible: visible(document.querySelector(
      '.u-homework-evaAction .xlinfo .j-gotonext'
    )),
    resultVisible: visible(document.querySelector('.u-homework-evaAction .xlinfo')),
    noPending,
    successText: ['提交成功', '评价成功', '互评成功', '已提交评价']
      .some((needle) => text.includes(needle)),
    loginWall: /登录\s*\|\s*注册/.test(text) || text.includes('请登录后操作'),
    buttons: clickable.slice(0, 20),
  };
}
"""

CLICK_REVIEW_ENTRY_JS = r"""
(labels) => {
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
           style.display !== 'none' && style.visibility !== 'hidden';
  };
  const wanted = new Set(labels);
  const nodes = [...document.querySelectorAll('a,button,[role=button]')]
    .filter(visible)
    .map((el) => ({el, text: (el.innerText || '').trim()}))
    .filter((item) => item.text && item.text.length <= 30
      && !item.text.includes('自动互评'));
  const exact = nodes.find((item) => wanted.has(item.text));
  const partial = nodes.find((item) =>
    [...wanted].some((label) => item.text.includes(label)));
  const target = exact || partial;
  if (!target) return '';
  target.el.click();
  return target.text;
}
"""

SELECT_FULL_MARKS_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
           style.display !== 'none' && style.visibility !== 'hidden';
  };
  const roots = [...document.querySelectorAll(
    '.u-questionItem.u-analysisQuestion.analysisMode, ' +
    '.u-questionItem.u-analysisQuestion, .u-analysisQuestion, ' +
    '[class*="peerReview"] [class*="question"], [class*="PeerReview"] [class*="question"]'
  )].filter(visible);
  const selectedRoots = roots.length ? roots : [document];
  let groups = 0;
  let selected = 0;
  const clickLast = (candidates) => {
    const usable = candidates.filter(visible);
    if (!usable.length) return false;
    const target = usable[usable.length - 1];
    const label = target.closest('label') || target;
    label.click();
    const input = target.matches('input')
      ? target : target.querySelector('input');
    if (input) {
      if (input.type === 'radio' || input.type === 'checkbox') {
        input.checked = true;
      }
      input.dispatchEvent(new Event('input', {bubbles: true}));
      input.dispatchEvent(new Event('change', {bubbles: true}));
    }
    return true;
  };
  selectedRoots.forEach((root) => {
    const scoreGroups = [...root.querySelectorAll('.s')].filter(visible);
    if (scoreGroups.length) {
      scoreGroups.forEach((group) => {
        groups += 1;
        const options = [...group.querySelectorAll(
          'input[type=radio],input[type=checkbox],[role=radio],label'
        )].filter(visible);
        if (clickLast(options)) selected += 1;
      });
      return;
    }
    const byName = new Map();
    [...root.querySelectorAll('input[type=radio],input[type=checkbox],[role=radio]')]
      .filter(visible)
      .forEach((el) => {
        const key = el.getAttribute('name') || el.getAttribute('aria-label')
          || el.parentElement?.className || 'default';
        if (!byName.has(key)) byName.set(key, []);
        byName.get(key).push(el);
      });
    byName.forEach((options) => {
      groups += 1;
      if (clickLast(options)) selected += 1;
    });
  });
  return {groups, selected};
}
"""

FILL_COMMENT_JS = r"""
(text) => {
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
           style.display !== 'none' && style.visibility !== 'hidden';
  };
  const fields = [...document.querySelectorAll(
    'textarea, [contenteditable="true"]'
  )].filter(visible);
  let filled = 0;
  fields.forEach((field) => {
    if (field.tagName === 'TEXTAREA') {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value'
      )?.set;
      if (setter) setter.call(field, text); else field.value = text;
      field.dispatchEvent(new Event('input', {bubbles: true}));
      field.dispatchEvent(new Event('change', {bubbles: true}));
    } else {
      field.textContent = text;
      field.dispatchEvent(new InputEvent('input', {bubbles: true, data: text}));
    }
    filled += 1;
  });
  return filled;
}
"""


class ReviewPage(PageObject):
    """作业互评页。"""

    def state(self) -> dict[str, Any]:
        """读取互评页状态。"""
        assert self.page is not None
        try:
            return dict(self.page.evaluate(REVIEW_PAGE_STATE_JS) or {})
        except Exception:
            return {}

    def click_entry(self) -> str:
        """点击“前往互评/开始互评”等入口。"""
        assert self.page is not None
        try:
            return str(
                self.page.evaluate(CLICK_REVIEW_ENTRY_JS, list(REVIEW_ENTRY_TEXTS))
                or ""
            )
        except Exception:
            return ""

    def select_full_marks(self) -> dict[str, int]:
        """选择每组评分项的最后一项（满分）。"""
        assert self.page is not None
        data: Any = self.page.evaluate(SELECT_FULL_MARKS_JS) or {}
        return {
            "groups": int((data or {}).get("groups") or 0),
            "selected": int((data or {}).get("selected") or 0),
        }

    def fill_comment(self, text: str) -> int:
        """填写评语并触发输入事件。"""
        assert self.page is not None
        return int(self.page.evaluate(FILL_COMMENT_JS, str(text)) or 0)

    def click_selector(self, selector: str, *, timeout: int = 3000) -> bool:
        """点击第一个可见匹配元素。"""
        assert self.page is not None
        try:
            for locator in self.page.locator(selector).all():
                if locator.is_visible(timeout=timeout):
                    locator.click(timeout=timeout)
                    return True
        except Exception:
            pass
        return False

    def click_submit(self) -> bool:
        """点击提交互评。"""
        return self.click_selector(REVIEW_SELECTORS["submit"])

    def click_next(self) -> bool:
        """点击下一份互评。"""
        return self.click_selector(REVIEW_SELECTORS["next"])

    def signature(self) -> str:
        """返回当前互评题目签名，用于防止“下一份”循环重复。"""
        assert self.page is not None
        try:
            return str(
                self.page.evaluate(
                    "() => (document.body?.innerText || '').slice(0, 600)"
                )
                or ""
            )
        except Exception:
            return ""
