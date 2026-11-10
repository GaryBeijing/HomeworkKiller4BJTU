# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-10 13:00
# 文件名: popup_page.py
# 主要用途: 视频弹题 Page Object：弹题选择器、检测、填空与继续按钮脚本。
# 文件版本: 4.4.0
"""视频弹题页面常量。"""
from __future__ import annotations

__version__ = "4.4.0"
__author__ = "Gary"
__all__ = ["CONTINUE_JS", "DETECT_JS", "FILL_TEXT_JS", "POPUP_SELECTORS"]


POPUP_SELECTORS = (
    ".u-questionItem",
    ".m-choiceQuestion",
    "[class*=popupQuestion]",
    "[class*=videoQuestion]",
)

DETECT_JS = r"""
(selectors) => {
  for (const sel of selectors) {
    for (const el of document.querySelectorAll(sel)) {
      const rect = el.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) continue;
      const titleEl = el.querySelector(
        '.j-title .j-richTxt, .j-richTxt, .questionTitle, [class*=title]'
      );
      const inputs = [...el.querySelectorAll(
        'input.u-tbi, input[type=radio], input[type=checkbox]'
      )];
      const optionTexts = [...el.querySelectorAll('.optionCnt, label')]
        .map(node => (node.innerText || '').trim())
        .filter(Boolean);
      return {
        title: ((titleEl && titleEl.innerText) || el.innerText || '').trim().slice(0, 800),
        optionTexts,
        inputs: inputs.map(inp => ({id: inp.id, type: inp.type, checked: inp.checked})),
      };
    }
  }
  return null;
}
"""

FILL_TEXT_JS = r"""
(value) => {
  const sels = [
    '.u-questionItem input[type=text]',
    '.u-questionItem textarea',
    '[class*=popupQuestion] input[type=text]',
    '[class*=popupQuestion] textarea'
  ];
  for (const sel of sels) {
    for (const el of document.querySelectorAll(sel)) {
      const rect = el.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) continue;
      const proto = el.tagName === 'TEXTAREA'
        ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(el, value);
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      return true;
    }
  }
  return false;
}
"""

CONTINUE_JS = r"""
() => {
  const labels = ['继续', '继续播放', '确定', '提交', '知道了'];
  const nodes = [...document.querySelectorAll('button,a,span,.u-btn,.ux-btn')];
  for (const node of nodes) {
    const text = (node.innerText || '').trim();
    if (!labels.includes(text)) continue;
    if (node.getBoundingClientRect().height > 0) {
      node.click();
      return text;
    }
  }
  return '';
}
"""
