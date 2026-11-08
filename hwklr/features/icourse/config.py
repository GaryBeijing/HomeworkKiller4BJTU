# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: config.py
# 主要用途: 中国大学慕课功能的常量、站点地址与外部会话/下载/截图路径。
# 文件版本: 4.0.0
"""中国大学慕课功能的路径与常量。

所有用户数据都放在程序根目录（``hwklr.config.app_root``）下：
``auth/`` 保存会话与浏览器配置，``documents/icourse/`` 保存课件，
``artifacts/icourse/`` 保存失败截图。
"""
from __future__ import annotations

from pathlib import Path

from hwklr.config import app_root

APP_NAME = "icourse"

BASE_URL = "https://www.icourse163.org"
LOGIN_PAGE = f"{BASE_URL}/member/login.htm"
LOGIN_ENDPOINT = f"{BASE_URL}/passport/reg/icourseLogin.do"
RPC_BASE = f"{BASE_URL}/web/j/"
BIFROST_RPC_BASE = f"{BASE_URL}/mm-bifrost/web/j/"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

PAGE_SIZE = 50
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3


def auth_dir() -> Path:
    """返回会话与浏览器配置目录。

    Returns:
        ``app_root()/auth``。
    """
    return app_root() / "auth"


def session_file() -> Path:
    """返回主会话文件路径。

    Returns:
        ``auth/icourse_session.json``。
    """
    return auth_dir() / "icourse_session.json"


def spoc_session_file() -> Path:
    """返回 SPOC/学校云专用会话文件路径。

    Returns:
        ``auth/icourse_spoc_session.json``。
    """
    return auth_dir() / "icourse_spoc_session.json"


def storage_state_file() -> Path:
    """返回 Playwright storage_state 文件路径。

    Returns:
        ``auth/icourse_storage_state.json``。
    """
    return auth_dir() / "icourse_storage_state.json"


def browser_profile_dir() -> Path:
    """返回窗口登录使用的独立 Edge 配置目录。

    Returns:
        ``auth/edge-profile``。
    """
    return auth_dir() / "edge-profile"


def browser_port_file() -> Path:
    """返回窗口登录的 CDP 端口文件路径。

    Returns:
        ``auth/edge-port.txt``。
    """
    return auth_dir() / "edge-port.txt"


def documents_dir() -> Path:
    """返回课件下载根目录。

    Returns:
        ``app_root()/documents/icourse``。
    """
    return app_root() / "documents" / APP_NAME


def artifacts_dir() -> Path:
    """返回失败截图目录。

    Returns:
        ``app_root()/artifacts/icourse``。
    """
    return app_root() / "artifacts" / APP_NAME
