# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-03 17:10
# 文件名: versions.py
# 主要用途: 统一软件版本与插件版本在“关于”页、构建命名中的显示格式。
# 文件版本: 3.0.0
"""版本号显示格式。

V3 起应用与插件使用不同的展示规则：

- 软件版本：``A.B.C.D`` → ``vA.B.PatchC-bD``（例如 ``3.1.3.3456`` →
  ``v3.1.Patch3-b3456``）；
- 插件版本：``[a/b/r/v]A.B.C.D`` → ``前缀A.BpC-bD``（例如
  ``r1.5.3.6`` → ``r1.5p3-b6``）。
"""
from __future__ import annotations

import re
from typing import Final

__version__ = "3.0.0"
__author__ = "Gary"
__all__ = ["format_app_version", "format_plugin_version", "split_version"]

_VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?P<prefix>[abrvABRV]?)(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:\.(?P<build>\d+))?$"
)


def split_version(version: str) -> tuple[str, str, str, str, str] | None:
    """拆解版本号。

    Args:
        version: 原始版本号，可带 ``a`` / ``b`` / ``r`` / ``v`` 前缀。

    Returns:
        ``(前缀, 主版本, 次版本, 修订号, 构建号)``；格式不合法时返回 ``None``。
    """
    match: re.Match[str] | None = _VERSION_PATTERN.match(str(version or "").strip())
    if match is None:
        return None
    return (
        match.group("prefix") or "",
        match.group("major"),
        match.group("minor"),
        match.group("patch"),
        match.group("build") or "0",
    )


def format_app_version(version: str) -> str:
    """按软件规则格式化版本号。

    Args:
        version: ``A.B.C`` 或 ``A.B.C.D`` 形式的版本号。

    Returns:
        ``vA.B.PatchC-bD``；格式不合法时原样返回。
    """
    parts = split_version(version)
    if parts is None:
        return str(version or "")
    _prefix, major, minor, patch, build = parts
    return "v%s.%s.Patch%s-b%s" % (major, minor, patch, build)


def format_plugin_version(version: str) -> str:
    """按插件规则格式化版本号。

    Args:
        version: 可带 ``a`` / ``b`` / ``r`` / ``v`` 前缀的版本号。

    Returns:
        ``前缀A.BpC-bD``；格式不合法时原样返回。
    """
    parts = split_version(version)
    if parts is None:
        return str(version or "")
    prefix, major, minor, patch, build = parts
    return "%s%s.%sp%s-b%s" % (prefix, major, minor, patch, build)
