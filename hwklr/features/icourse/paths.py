# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: paths.py
# 主要用途: 兼容原型模块的路径函数，统一指向程序外侧的 auth/documents/artifacts/db 目录。
# 文件版本: 4.0.0
"""慕课功能的路径兼容层。

原型动作/浏览器模块通过本模块获取数据目录；本项目统一把用户数据放在
``hwklr.config.app_root()`` 下，数据库目录复用 ``hwklr.db.db_dir``。
"""
from __future__ import annotations

from pathlib import Path

from hwklr.config import app_root
from hwklr.db import db_dir as _db_dir

from . import config


def project_root() -> Path:
    """返回程序根目录。

    Returns:
        ``hwklr.config.app_root()``。
    """
    return app_root()


def data_dir() -> Path:
    """返回功能数据根目录。

    Returns:
        程序根目录。
    """
    return app_root()


def db_dir() -> Path:
    """返回数据库目录。

    Returns:
        ``hwklr.db.db_dir()``（程序根目录下的 ``db/``）。
    """
    return _db_dir()


def documents_dir() -> Path:
    """返回课件下载目录。

    Returns:
        ``documents/icourse``。
    """
    return config.documents_dir()


def artifacts_dir() -> Path:
    """返回截图目录。

    Returns:
        ``artifacts/icourse``。
    """
    return config.artifacts_dir()


def spoc_session_file() -> Path:
    """返回 SPOC 专用会话文件。

    Returns:
        ``auth/icourse_spoc_session.json``。
    """
    return config.spoc_session_file()
