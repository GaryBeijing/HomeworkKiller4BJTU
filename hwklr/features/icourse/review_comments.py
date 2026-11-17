# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-17 10:00
# 最后更新: 2026-11-17 10:00
# 文件名: review_comments.py
# 主要用途: 加载互评常用评语库，并提供不放回随机抽取。
# 文件版本: 4.7.0
"""自动互评评语库。"""
from __future__ import annotations

import random
from typing import Any, Iterable

from hwklr.runtime_data import load_bank

__version__ = "4.7.0"
__author__ = "Gary"
__all__ = ["CommentPicker", "load_comments"]

_BANK_KEY = "icourse_comments"


def load_comments() -> list[str]:
    """读取并清理评语库。

    Returns:
        非空、去重后的评语列表。

    Raises:
        ValueError: 评语库缺失或为空。
    """
    data: Any = load_bank(_BANK_KEY)
    if isinstance(data, dict):
        data = data.get("comments")
    if not isinstance(data, list):
        raise ValueError("互评评语库格式异常")
    comments: list[str] = []
    for item in data:
        text = str(item).strip() if isinstance(item, str) else ""
        if text:
            comments.append(text)
    if not comments:
        raise ValueError("互评评语库为空")
    return comments


class CommentPicker:
    """不放回随机抽取评语；抽完自动重新洗牌。"""

    def __init__(
        self,
        comments: Iterable[str] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        """初始化 picker。

        Args:
            comments: 评语列表；空值时读取内置评语库。
            rng: 可注入的随机源（测试用）。
        """
        source = list(comments) if comments is not None else load_comments()
        self._comments: list[str] = [str(item).strip() for item in source if str(item).strip()]
        if not self._comments:
            raise ValueError("没有可用的互评评语")
        self._rng: random.Random = rng or random.Random()
        self._order: list[int] = []
        self._last: str = ""

    def _refill(self) -> None:
        self._order = list(range(len(self._comments)))
        self._rng.shuffle(self._order)
        # 重新洗牌后避免紧接着重复上一条。
        if len(self._order) > 1 and self._comments[self._order[-1]] == self._last:
            self._order[-1], self._order[-2] = self._order[-2], self._order[-1]

    def next(self) -> str:
        """返回下一条不重复评语。"""
        if not self._order:
            self._refill()
        text = self._comments[self._order.pop()]
        self._last = text
        return text
