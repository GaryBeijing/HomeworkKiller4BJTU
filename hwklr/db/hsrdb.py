# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 13:26
# 文件名: hsrdb.py
# 主要用途: 高铁纵横题库的 DbProvider 实现：从 hsrdb 源描述读取内置题库并缓存到外部 db/hsr1.json。
# 文件版本: 3.1.0
"""高铁纵横数据库。

首次加载时通过 ``super().fetch(1)`` 读取 ``hsr_sources.json`` 指向的
``runtime_data/hsr_bank_v1.0.json``，把题库包装为带版本元信息的 JSON 对象，
并写入外部 ``db/hsr1.json``；后续加载直接读取缓存文件。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from .provider import DbFormatError, DbProvider, DbSourceNotFoundError

__version__ = "3.1.0"
__author__ = "Gary"
__all__ = ["HSRDb"]

# 高铁知识库在数据库中的固定记录编号。
HSR_DB_ID: Final[int] = 1


class HSRDb(DbProvider):
    """高铁纵横题库提供者。"""

    def __init__(
        self,
        db_root: Path | None = None,
        source_root: Path | None = None,
    ) -> None:
        """初始化高铁题库 provider。

        Args:
            db_root: 数据库目录覆盖值；``None`` 时使用外部 ``db/``。
            source_root: 源描述目录覆盖值；``None`` 时使用 ``hwklr/db/``。
        """
        super().__init__("hsr", db_root=db_root, source_root=source_root)

    def fetch(self, id: int) -> dict[str, Any]:
        """抓取并缓存高铁题库。

        Args:
            id: 记录编号，目前仅支持 :data:`HSR_DB_ID`（1）。

        Returns:
            含 ``items`` 与版本元信息的 JSON 对象。

        Raises:
            DbSourceNotFoundError: id 不受支持或源文件缺失。
            DbFormatError: 源题库不是 JSON 数组。
        """
        if id != HSR_DB_ID:
            raise DbSourceNotFoundError(
                "高铁数据库仅支持 id=%d，收到 id=%s" % (HSR_DB_ID, id)
            )
        entry: dict[str, Any] = self._source_entry(id)
        raw: Any = super().fetch(id)
        if not isinstance(raw, list):
            raise DbFormatError("高铁题库源文件必须是 JSON 数组")
        versions: list[str] = self._source_versions()
        version: str = str(entry.get("version") or (versions[0] if versions else ""))
        if version and version not in versions:
            versions = [version, *versions]
        payload: dict[str, Any] = {
            "schema": 1,
            "base_name": self.base_name,
            "id": id,
            "feature": str(entry.get("feature") or self.base_name),
            "version": version,
            "versions": versions,
            "latest_version": versions[0] if versions else version,
            "count": len(raw),
            "items": raw,
        }
        self._dump(id, payload)
        return payload

    def bank_info(self) -> list[dict[str, Any]]:
        """返回设置页展示用的题库信息。

        Returns:
            单行 ``[{feature, version, count}]``。
        """
        payload: dict[str, Any] = self.load(HSR_DB_ID)
        items: Any = payload.get("items")
        count: int = int(
            payload.get("count")
            if isinstance(payload.get("count"), int)
            else (len(items) if isinstance(items, list) else 0)
        )
        return [
            {
                "feature": self.base_name,
                "version": str(payload.get("version") or ""),
                "count": count,
            }
        ]
