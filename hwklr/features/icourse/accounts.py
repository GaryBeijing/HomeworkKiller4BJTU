# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-12 10:00
# 文件名: accounts.py
# 主要用途: 账号类型到登录方式的路由；已删除“自动识别”，由用户显式选择账号类型。
# 文件版本: 4.6.0
"""账号类型路由。

- 爱课堂/爱课程账号：手机号或邮箱注册，走登录页的「爱课程登录」表单；
- 网易通行证邮箱：走 URS「邮箱登录」；
- 网易通行证手机号：走 URS「手机号登录」。

浏览器登录页：https://www.icourse163.org/member/login.htm
- 爱课程登录：主页面表单（账号/密码）
- 邮箱登录：URS iframe（input[name=email][type=text]）
- 手机号登录：URS iframe（input[name=email][type=tel]）
"""

from __future__ import annotations

from typing import Literal

AccountKind = Literal["aiketang", "netease", "netease_phone"]
AccountType = Literal[
    "aiketang", "icourse", "netease", "netease_phone", "mail", "phone"
]

_AIKETANG_ALIASES = {"aiketang", "icourse"}
_NETEASE_ALIASES = {"netease", "mail"}
_NETEASE_PHONE_ALIASES = {"netease_phone", "phone"}


def resolve_account_type(explicit: str | None) -> AccountKind:
    """把用户显式选择的账号类型转换为内部登录类型。

    “自动识别”已删除；空值或未知值回退到爱课程，不再根据账号内容猜测。
    """
    value: str = (explicit or "icourse").strip().lower()
    if value in _NETEASE_ALIASES:
        return "netease"
    if value in _NETEASE_PHONE_ALIASES:
        return "netease_phone"
    if value in _AIKETANG_ALIASES:
        return "aiketang"
    return "aiketang"


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
