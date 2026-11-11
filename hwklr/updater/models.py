# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-11 21:00
# 文件名: models.py
# 主要用途: 更新器与平台安装器之间传递的 release、资产与准备结果数据结构。
# 文件版本: 4.5.0
"""更新器数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__version__ = "4.5.0"
__author__ = "Gary"
__all__ = ["PreparedUpdate", "ReleaseAsset", "ReleaseInfo"]


@dataclass(frozen=True)
class ReleaseAsset:
    """一个 release 资产。"""

    name: str
    url: str
    size: int = 0
    digest: str = ""


@dataclass
class ReleaseInfo:
    """归并后的 release 信息。"""

    tag: str
    source: str
    notes: str = ""
    release_url: str = ""
    assets: list[ReleaseAsset] = field(default_factory=list)

    @property
    def version(self) -> str:
        """去掉 v 前缀的版本号。"""
        return str(self.tag or "").lstrip("vV")


@dataclass
class PreparedUpdate:
    """已下载、校验并解压到 staging 的更新。"""

    version: str
    tag: str
    staged_dir: Path
    archive: Path
    entry: Path
    previous: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
