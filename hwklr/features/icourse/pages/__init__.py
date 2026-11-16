# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-16 20:30
# 文件名: __init__.py
# 主要用途: 页面适配层出口：URL、选择器与页面级操作。
# 文件版本: 4.6.7
"""页面适配层：URL、选择器与页面级操作。"""
from __future__ import annotations

from .icourse163 import (
    CONTENT_SELECTORS,
    DOCUMENT_SELECTORS,
    CourseUrls,
    click_tab,
    close_modals,
    content_url,
    forum_url,
    install_video_watch,
    is_spoc_url,
    learn_url,
    new_assessment_url,
    new_exam_list_url,
    new_learn_url,
    new_testlist_url,
    open_route,
    page_alerts,
    page_block_reason,
    seek_video,
    set_video_rate,
    testlist_url,
    video_state,
    wait_video_end,
)

__all__ = [
    "CONTENT_SELECTORS",
    "DOCUMENT_SELECTORS",
    "CourseUrls",
    "click_tab",
    "close_modals",
    "content_url",
    "forum_url",
    "install_video_watch",
    "is_spoc_url",
    "learn_url",
    "new_assessment_url",
    "new_exam_list_url",
    "new_learn_url",
    "new_testlist_url",
    "open_route",
    "page_alerts",
    "page_block_reason",
    "seek_video",
    "set_video_rate",
    "testlist_url",
    "video_state",
    "wait_video_end",
]
