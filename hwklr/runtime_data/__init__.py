# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 文件名: __init__.py
# 主要用途: 扫描并读取 hwklr/runtime_data 下按功能与版本存放的 JSON 知识库。
# 文件版本: 1.0.0
"""HomeworkKiller 知识库读取接口。

知识库以 JSON 文件按功能模块存放于本目录，命名规则::

    <feature>_bank_v<major>.<minor>.json

例如 ``hsr_bank_v1.0.json`` 表示「高铁纵横」功能的 1.0 版知识库。
本包只负责定位与读取文件，不包含任何功能业务逻辑。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

__version__ = "1.0.0"
__all__ = ["BANK_DIR", "list_banks", "list_versions", "latest_version", "load_bank"]
__author__ = "Gary"

BANK_DIR = Path(__file__).resolve().parent
_BANK_NAME = re.compile(
    r"^(?P<feature>[a-z0-9_]+)_bank_v(?P<version>\d+\.\d+)\.json$",
    re.IGNORECASE,
)


def _version_key(version: str) -> tuple[int, ...]:
    """把版本号转换为可比较的数字元组。

    Args:
        version: 形如 ``"1.0"`` 的版本字符串。

    Returns:
        由各段数字组成的元组。
    """
    return tuple(int(part) for part in version.split("."))


def _scan() -> dict[str, dict[str, Path]]:
    """扫描本目录，返回 {feature: {version: path}}。"""
    found: dict[str, dict[str, Path]] = {}
    for path in BANK_DIR.iterdir():
        match = _BANK_NAME.match(path.name)
        if not match or not path.is_file():
            continue
        feature = match.group("feature").lower()
        found.setdefault(feature, {})[match.group("version")] = path
    return found


def list_banks() -> dict[str, list[str]]:
    """返回 {功能名: [版本号, ...]}，版本按从新到旧排列。"""
    return {
        feature: sorted(versions, key=_version_key, reverse=True)
        for feature, versions in _scan().items()
    }


def list_versions(feature: str) -> list[str]:
    """返回指定功能的所有可用版本，从新到旧；功能不存在时返回空列表。"""
    return list_banks().get(feature.strip().lower(), [])


def latest_version(feature: str) -> str:
    """返回指定功能的最新版本号；功能不存在时抛出 FileNotFoundError。"""
    versions = list_versions(feature)
    if not versions:
        available = ", ".join(list_banks()) or "无"
        raise FileNotFoundError("未找到功能 %r 的知识库，可用功能: %s" % (feature, available))
    return versions[0]


def load_bank(feature: str, version: str | None = None) -> Any:
    """读取指定功能的知识库。

    ``version`` 为 None 时读取最新版本。返回 JSON 解析后的对象（通常是
    list 或 dict）。每次调用都会重新读取文件，调用方可安全修改返回值。
    """
    feature_key = feature.strip().lower()
    resolved = version or latest_version(feature_key)
    path = _scan().get(feature_key, {}).get(resolved)
    if path is None:
        raise FileNotFoundError("未找到知识库: %s_bank_v%s.json" % (feature_key, resolved))
    with path.open(encoding="utf-8-sig") as fp:
        return json.load(fp)
