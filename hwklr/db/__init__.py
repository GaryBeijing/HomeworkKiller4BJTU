# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 13:26
# 文件名: __init__.py
# 主要用途: 统一导出数据库机制：外部 db/ 目录、异常、DbProvider 基类、DbManager 与全局单例。
# 文件版本: 3.1.0
"""数据库机制。

- 数据文件存放在程序外侧的 ``db/`` 目录（与 ``config.json`` 同级）；
- 具体功能在 ``hwklr/db/`` 中实现 ``DbProvider`` 子类，并在
  :data:`hwklr.db.manager.PROVIDER_SPECS` 登记；
- ``Feature._load_db(id)`` 通过 :func:`get_db_manager` 获取对应 provider 并加载记录。
"""
from __future__ import annotations

from .manager import (
    PROVIDER_SPECS,
    DbManager,
    get_db_manager,
    init_db_manager,
)
from .provider import (
    DB_TIMEOUT,
    DbDisabledError,
    DbError,
    DbFormatError,
    DbProvider,
    DbProviderNotFoundError,
    DbSourceNotFoundError,
    DbStorageError,
    DbTimeoutError,
    db_dir,
)

__version__ = "3.1.0"
__author__ = "Gary"
__all__ = [
    "DB_TIMEOUT",
    "PROVIDER_SPECS",
    "DbDisabledError",
    "DbError",
    "DbFormatError",
    "DbManager",
    "DbProvider",
    "DbProviderNotFoundError",
    "DbSourceNotFoundError",
    "DbStorageError",
    "DbTimeoutError",
    "db_dir",
    "get_db_manager",
    "init_db_manager",
]
