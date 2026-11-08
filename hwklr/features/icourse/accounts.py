# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: accounts.py
# 主要用途: 账号类型识别与登录方式路由。
# 文件版本: 4.0.0
"""账号类型识别与登录路由。

- 爱课堂/爱课程账号：手机号或邮箱注册，走登录页的「爱课程登录」表单；
- 网易通行证：163/126/yeah 等邮箱，走 URS「邮箱登录」；
- 不能因为账号是手机号就默认走 URS「手机号登录」——爱课堂账号也是手机号。

浏览器登录页：https://www.icourse163.org/member/login.htm
- 爱课程登录：主页面表单（账号/密码）
- 邮箱登录：URS iframe（input[name=email][type=text]）
- 手机号登录：URS iframe（input[name=email][type=tel]）——仅网易手机号使用
"""

from __future__ import annotations

import re
from typing import Literal

AccountKind = Literal["aiketang", "netease", "netease_phone", "unknown"]
AccountType = Literal[
    "auto", "aiketang", "icourse", "netease", "netease_phone", "phone"
]

NETEASE_DOMAINS = {"163.com", "126.com", "yeah.net", "188.com", "vip.163.com"}
_PHONE = re.compile(r"^1[3-9]\d{9}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_AIKETANG_ALIASES = {"aiketang", "icourse", "phone"}


def detect_account_kind(identifier: str) -> AccountKind:
    """只按标识符判断；手机号默认视为爱课堂，不视为网易。"""
    text = str(identifier or "").strip()
    if not text:
        return "unknown"
    if "@" in text:
        domain = text.rsplit("@", 1)[-1].lower()
        return "netease" if domain in NETEASE_DOMAINS else "aiketang"
    if _PHONE.fullmatch(text):
        return "aiketang"
    if _EMAIL.fullmatch(text):
        return "aiketang"
    # 爱课堂也允许自定义账号；非邮箱一律按爱课堂处理。
    return "aiketang"


def resolve_account_type(explicit: str | None, identifier: str) -> AccountKind:
    value = (explicit or "auto").strip().lower()
    if value == "netease":
        return "netease"
    if value == "netease_phone":
        return "netease_phone"
    if value in _AIKETANG_ALIASES:
        return "aiketang"
    return detect_account_kind(identifier)


def prefers_browser(kind: AccountKind) -> bool:
    """两种账号都优先用浏览器登录页；HTTP 旧接口仅作为显式选项。"""
    return kind in ("aiketang", "netease", "netease_phone")


def allows_http_login(kind: AccountKind) -> bool:
    return kind == "aiketang"


def is_aiketang(kind: AccountKind) -> bool:
    return kind == "aiketang"


LOGIN_METHODS = ("phone", "mail", "icourse", "cookies")
LOGIN_METHOD_TO_KIND: dict[str, AccountKind] = {
    "phone": "netease_phone",  # 登录页「手机号登录」（URS）
    "mail": "netease",         # 登录页「邮箱登录」（URS）
    "icourse": "aiketang",     # 登录页「爱课程登录」（爱课堂手机号/邮箱）
}


def account_kind_for_method(method: str) -> AccountKind | None:
    return LOGIN_METHOD_TO_KIND.get((method or "").strip().lower())
