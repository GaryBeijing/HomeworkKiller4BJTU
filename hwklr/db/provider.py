# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 13:26
# 文件名: provider.py
# 主要用途: 定义数据库提供者基类 DbProvider、外部数据库目录解析、数据库异常与源文件读取。
# 文件版本: 3.1.0
"""数据库提供者基类。

数据文件统一存放在程序外侧的 ``db/`` 目录（与 ``config.json`` 同级），
文件名为 ``{base_name}{id}.json``。具体功能通过继承 :class:`DbProvider`
实现 :meth:`DbProvider.fetch`，并可选择调用 ``super().fetch(id)`` 复用
``{base_name}_sources.json`` 的源解析能力。

``{base_name}_sources.json`` 只是推荐的数据源描述方式，不是所有 provider
的必备文件：无法用源文件描述的数据（网络下载、动态计算等）可以在
:meth:`DbProvider.fetch` 中完整实现抓取逻辑。
"""
from __future__ import annotations

import abc
import contextlib
import json
import logging
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Final, final

from hwklr.config import app_root

__version__ = "3.1.0"
__author__ = "Gary"
__all__ = [
    "DB_TIMEOUT",
    "DbError",
    "DbDisabledError",
    "DbProviderNotFoundError",
    "DbSourceNotFoundError",
    "DbFormatError",
    "DbStorageError",
    "DbTimeoutError",
    "DbProvider",
    "db_dir",
]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
# 单个 provider 的并发加载等待上限（秒）。
DB_TIMEOUT: Final[int] = 15
_BASE_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_]+$")


class DbError(Exception):
    """数据库相关错误的基类。"""


class DbDisabledError(DbError):
    """功能未配置 ``_db_base_name`` 却尝试访问数据库时抛出。"""


class DbProviderNotFoundError(DbError):
    """``DbManager`` 中找不到指定数据库名称的 provider 时抛出。"""


class DbSourceNotFoundError(DbError):
    """``{base_name}_sources.json`` 或其中引用的源文件不存在时抛出。"""


class DbFormatError(DbError):
    """数据库文件或源文件不是合法的 JSON 对象/结构时抛出。"""


class DbStorageError(DbError):
    """数据库目录不可写、落盘失败或 fetch 未产生数据时抛出。"""


class DbTimeoutError(DbError):
    """等待同一 provider 释放加载锁超过 ``DB_TIMEOUT`` 时抛出。"""


def db_dir() -> Path:
    """返回外部数据库目录。

    目录与 ``config.json`` 位于同一程序根：源码运行时是项目根，
    PyInstaller 打包后是可执行文件同级，V3 ``HwklrVenv`` 中是虚拟环境根。
    目录本身在首次落盘时才创建。

    Returns:
        ``db/`` 的绝对路径。
    """
    return app_root() / "db"


def _normalize_id(value: Any) -> int:
    """校验并规范化数据库 id。

    Args:
        value: 调用方传入的 id。

    Returns:
        非负整数 id。

    Raises:
        TypeError: 不是整数（``bool`` 也不算）。
        ValueError: 为负数。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("数据库 id 必须是整数")
    if value < 0:
        raise ValueError("数据库 id 不能为负数")
    return value


class DbProvider(abc.ABC):
    """数据库提供者基类。

    子类必须实现 :meth:`fetch`，并在抓取成功后调用 :meth:`_dump` 持久化；
    若 ``fetch`` 直接返回了 JSON 对象，:meth:`load` 也会兜底落盘。
    """

    def __init__(
        self,
        base_name: str,
        db_root: Path | None = None,
        source_root: Path | None = None,
    ) -> None:
        """初始化 provider。

        Args:
            base_name: 数据库名称，例如 ``"hsr"``；只能包含字母、数字和下划线。
            db_root: 数据库目录覆盖值；``None`` 时使用 :func:`db_dir`（测试用）。
            source_root: ``*_sources.json`` 所在目录；``None`` 时使用本模块目录。

        Raises:
            ValueError: ``base_name`` 为空或包含非法字符。
        """
        name: str = str(base_name or "").strip()
        if not name or not _BASE_NAME_PATTERN.match(name):
            raise ValueError("非法数据库名称: %r" % base_name)
        self._base_name: str = name
        self._db_root: Path | None = Path(db_root) if db_root is not None else None
        self._source_root: Path | None = (
            Path(source_root) if source_root is not None else None
        )
        self._lock: threading.RLock = threading.RLock()

    @property
    @final
    def base_name(self) -> str:
        """返回数据库名称。

        Returns:
            例如 ``"hsr"``。
        """
        return self._base_name

    @property
    def db_root(self) -> Path:
        """返回数据库目录。

        Returns:
            测试注入的目录，或 :func:`db_dir` 的结果。
        """
        return self._db_root if self._db_root is not None else db_dir()

    @property
    def source_root(self) -> Path:
        """返回源描述文件所在目录。

        Returns:
            测试注入的目录，或 ``hwklr/db``（本模块所在目录）。
        """
        return (
            self._source_root
            if self._source_root is not None
            else Path(__file__).resolve().parent
        )

    @final
    def exist(self, id: int) -> bool:
        """检查指定 id 的数据库文件是否存在。

        Args:
            id: 数据库记录编号。

        Returns:
            存在返回 ``True``，否则返回 ``False``。
        """
        return self._db_path(_normalize_id(id)).is_file()

    @final
    def load(self, id: int) -> Any:
        """读取数据库；不存在时调用 :meth:`fetch` 抓取并落盘。

        流程遵循 version3.1.0 需求：``exist`` → 读取 → ``fetch`` → 重新读取。
        损坏的缓存文件会被删除并重建，避免永久卡死。

        Args:
            id: 数据库记录编号。

        Returns:
            数据库中的 JSON 对象；``fetch`` 返回 ``None`` 且未落盘时为 ``None``。

        Raises:
            DbFormatError: 数据库文件不是 JSON 对象。
            DbStorageError: ``fetch`` 未产生可读取的数据。
            DbTimeoutError: 等待其他线程完成加载超时。
        """
        identifier: int = _normalize_id(id)
        with self._guard():
            if self.exist(identifier):
                try:
                    return self._read(identifier)
                except DbFormatError as exc:
                    # #缓存自愈：损坏文件按一次未命中处理，fetch 成功后覆盖重建。
                    _LOGGER.warning(
                        "数据库缓存损坏，将重新生成 %s: %s",
                        self._db_path(identifier),
                        exc,
                    )
                    try:
                        self._db_path(identifier).unlink()
                    except OSError:
                        pass
            payload: Any = self.fetch(identifier)
            if not self.exist(identifier):
                if payload is None:
                    return None
                self._dump(identifier, payload)
            return self._read(identifier)

    @abc.abstractmethod
    def fetch(self, id: int) -> Any:
        """抓取指定 id 的数据。

        推荐实现方式：调用 ``super().fetch(id)`` 读取 ``{base_name}_sources.json``
        中匹配的源文件，再做必要的转换后调用 :meth:`_dump`。若数据无法用源文件
        描述，也可以完全忽略 ``super().fetch(id)``，在此方法内实现完整抓取逻辑。

        Args:
            id: 数据库记录编号。

        Returns:
            抓取到的 JSON 数据；``None`` 表示没有可用数据。

        Raises:
            DbSourceNotFoundError: 选择源文件路径但源文件缺失或 id 不匹配。
            DbFormatError: 源文件结构不合法。
        """
        return self._read_source(self._source_entry(id))

    @final
    def _dump(self, id: int, payload: Any) -> None:
        """把 JSON 对象原子写入数据库目录。

        Args:
            id: 数据库记录编号。
            payload: 待写入的 JSON 对象，必须是 ``dict``。

        Raises:
            DbFormatError: ``payload`` 不是 JSON 对象。
            DbStorageError: 目录不可写或写入失败。
        """
        identifier: int = _normalize_id(id)
        if not isinstance(payload, dict):
            raise DbFormatError(
                "数据库 %s 的 id=%s 必须是 JSON 对象" % (self._base_name, identifier)
            )
        target: Path = self._db_path(identifier)
        parent: Path = target.parent
        with self._guard():
            try:
                parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(
                    prefix=".%s-" % target.name,
                    suffix=".tmp",
                    dir=str(parent),
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        json.dump(payload, handle, ensure_ascii=False, indent=2)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, target)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            except (OSError, TypeError, ValueError) as exc:
                raise DbStorageError(
                    "写入数据库 %s 失败: %s" % (target, exc)
                ) from exc

    def bank_info(self) -> list[dict[str, Any]]:
        """返回设置页“知识库”表格所需的记录信息。

        默认不展示；需要展示的功能可覆盖此方法。

        Returns:
            形如 ``[{"feature": str, "version": str, "count": int}]`` 的列表。
        """
        return []

    def _guard(self) -> contextlib.AbstractContextManager[None]:
        """获取 provider 加载锁。

        Returns:
            上下文管理器；退出时自动释放锁。

        Raises:
            DbTimeoutError: 超过 ``DB_TIMEOUT`` 仍未获取到锁。
        """
        return _ProviderGuard(self._lock, self._base_name)

    def _db_path(self, id: int) -> Path:
        """构造数据库文件路径。

        Args:
            id: 已规范化的记录编号。

        Returns:
            ``{db_root}/{base_name}{id}.json``。
        """
        return self.db_root / ("%s%d.json" % (self._base_name, id))

    def _read(self, id: int) -> Any:
        """读取数据库 JSON 文件。

        Args:
            id: 已规范化的记录编号。

        Returns:
            JSON 对象。

        Raises:
            DbFormatError: 文件缺失、无法解析或根节点不是对象。
        """
        path: Path = self._db_path(id)
        try:
            with path.open(encoding="utf-8-sig") as handle:
                data: Any = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise DbFormatError("读取数据库失败 %s: %s" % (path, exc)) from exc
        if not isinstance(data, dict):
            raise DbFormatError("数据库 %s 的根节点必须是 JSON 对象" % path)
        return data

    def _source_entry(self, id: int) -> dict[str, Any]:
        """从 ``{base_name}_sources.json`` 中查找 id 对应的源条目。

        支持两种结构：``{"sources": [...]}`` 或直接的数组。

        Args:
            id: 数据库记录编号。

        Returns:
            匹配的源条目。

        Raises:
            DbSourceNotFoundError: 源描述文件不存在、没有匹配条目或缺少 path。
            DbFormatError: 源描述文件不是合法 JSON 或结构不合法。
        """
        path: Path = self.source_root / ("%s_sources.json" % self._base_name)
        if not path.is_file():
            raise DbSourceNotFoundError("未找到源描述文件: %s" % path)
        try:
            with path.open(encoding="utf-8-sig") as handle:
                data: Any = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise DbFormatError("读取源描述文件失败 %s: %s" % (path, exc)) from exc
        entries: Any = data.get("sources") if isinstance(data, dict) else data
        if not isinstance(entries, list):
            raise DbFormatError("源描述文件缺少 sources 数组: %s" % path)
        for entry in entries:
            if isinstance(entry, dict) and entry.get("id") == id:
                if not str(entry.get("path") or "").strip():
                    raise DbSourceNotFoundError(
                        "源条目 id=%s 缺少 path: %s" % (id, path)
                    )
                return dict(entry)
        raise DbSourceNotFoundError(
            "源描述文件 %s 中没有 id=%s 的条目" % (path, id)
        )

    def _source_versions(self) -> list[str]:
        """读取源描述文件中的版本号列表。

        Returns:
            去重后的版本号列表（保持出现顺序）；文件缺失或损坏时返回空列表。
        """
        path: Path = self.source_root / ("%s_sources.json" % self._base_name)
        try:
            with path.open(encoding="utf-8-sig") as handle:
                data: Any = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return []
        entries: Any = data.get("sources") if isinstance(data, dict) else data
        if not isinstance(entries, list):
            return []
        versions: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            version: str = str(entry.get("version") or "").strip()
            if version and version not in versions:
                versions.append(version)
        return versions

    def _read_source(self, entry: dict[str, Any]) -> Any:
        """读取源条目指向的 JSON 文件。

        Args:
            entry: :meth:`_source_entry` 返回的源条目。

        Returns:
            解析后的 JSON 数据。

        Raises:
            DbSourceNotFoundError: 源文件不存在或路径越界。
            DbFormatError: 源文件无法解析。
        """
        raw_path: str = str(entry.get("path") or "").strip()
        package_root: Path = Path(__file__).resolve().parent.parent
        target: Path = (package_root / raw_path).resolve()
        if not target.is_relative_to(package_root):
            raise DbSourceNotFoundError("源文件路径越界: %s" % raw_path)
        if not target.is_file():
            raise DbSourceNotFoundError("源文件不存在: %s" % target)
        try:
            with target.open(encoding="utf-8-sig") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise DbFormatError("读取源文件失败 %s: %s" % (target, exc)) from exc


class _ProviderGuard:
    """``DbProvider`` 的带超时加载锁。"""

    def __init__(self, lock: threading.RLock, base_name: str) -> None:
        """初始化锁包装。

        Args:
            lock: provider 持有的可重入锁。
            base_name: 数据库名称，用于错误信息。
        """
        self._lock: threading.RLock = lock
        self._base_name: str = base_name

    def __enter__(self) -> None:
        """获取锁。

        Raises:
            DbTimeoutError: 等待超时。
        """
        if not self._lock.acquire(timeout=DB_TIMEOUT):
            raise DbTimeoutError(
                "等待数据库 %s 加载超时（%d 秒）" % (self._base_name, DB_TIMEOUT)
            )

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """释放锁。"""
        self._lock.release()
