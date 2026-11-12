# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-12 13:00
# 最后更新: 2026-11-12 13:00
# 文件名: welcome.py
# 主要用途: 首次启动/版本升级后的欢迎弹窗数据：读取协议与更新说明、解析更新条目并记录已确认版本。
# 文件版本: 4.6.1
"""欢迎弹窗数据。

协议与更新说明来自发行包根目录的 ``LICENSE``、``usr_agreement.txt`` 与
``updates_info.txt``。源码运行时回退到项目根目录，打包运行时按数据目录、
安装根目录与可执行文件所在目录依次查找，兼容“exe 同级”和版本化安装布局。
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any, Final

from hwklr import __version__ as APP_VERSION
from hwklr.config import data_root, install_root, load_config, update_config

__version__ = "4.6.1"
__author__ = "Gary"
__all__ = [
    "load_agreement_text",
    "load_updates",
    "mark_welcome_seen",
    "parse_updates",
    "welcome_payload",
]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_AGREEMENT_FILE: Final[str] = "usr_agreement.txt"
_LICENSE_FILE: Final[str] = "LICENSE"
_UPDATES_FILE: Final[str] = "updates_info.txt"
_WELCOME_TITLE: Final[str] = "欢迎使用北交作业助手v%s！"
_WELCOME_SUBTITLE: Final[str] = "让我们共创北交美好生活( •̀ᴗ•́ )و"
_AGREEMENT_HEADING: Final[str] = "使用本软件前，您需要知悉我们的协议："
_UPDATES_HEADING: Final[str] = "v%s新功能一览！！"

_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^\s*#{1,6}\s*(.+?)\s*$")
_BRACKET_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^\s*[【\[](.+?)[】\]]\s*$")
_BULLET_RE: Final[re.Pattern[str]] = re.compile(r"^\s*[-*·•]\s+(.+?)\s*$")
_COLON_GROUP_RE: Final[re.Pattern[str]] = re.compile(r"^([^:：]+)[:：]\s*(.+)$")


def _resource_roots() -> tuple[Path, ...]:
    """返回按优先级排列的资源查找根目录。

    Returns:
        去重后的目录列表；不存在的目录也会保留，由读取逻辑跳过。
    """
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        executable: Path = Path(sys.executable).resolve()
        # 当前版本目录优先，避免版本化安装根目录中残留的旧更新说明被误用。
        # Windows 的说明文件与 exe 同级；macOS 的发行包位于 .app 同级，
        # 因此继续向上查找若干层，覆盖 <v>/App.app/Contents/MacOS/App。
        roots.append(executable.parent)
        roots.extend(list(executable.parents)[:5])
        meipass: Any = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(str(meipass)))
    roots.extend([data_root(), install_root()])
    # 源码运行：hwklr/welcome.py -> hwklr -> 项目根目录。
    roots.append(Path(__file__).resolve().parent.parent)
    roots.append(Path(__file__).resolve().parent)
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key: str = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return tuple(unique)


def _read_text(name: str) -> str:
    """在资源根目录中查找并读取 UTF-8 文本。

    Args:
        name: 文件名（不带路径）。

    Returns:
        文件内容；不存在或读取失败时返回空字符串。
    """
    for root in _resource_roots():
        path: Path = root / name
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            _LOGGER.warning("读取欢迎页资源失败 %s: %s", path, exc)
    return ""


def load_agreement_text() -> str:
    """合并开源许可证与用户协议文本。

    Returns:
        供弹窗滚动区展示的完整文本。
    """
    sections: list[str] = []
    license_text: str = _read_text(_LICENSE_FILE).strip()
    if license_text:
        sections.append("【开源许可证】\n" + license_text)
    agreement_text: str = _read_text(_AGREEMENT_FILE).strip()
    if agreement_text:
        sections.append("【用户协议】\n" + agreement_text)
    return "\n\n".join(sections) or "暂无协议内容。"


def _compact_group(segment: str) -> dict[str, Any] | None:
    """解析 ``分类 条目1 条目2`` 形式的单行分组。

    Args:
        segment: 以分号分隔的一段文本。

    Returns:
        分组字典；没有有效内容时返回 ``None``。
    """
    tokens: list[str] = segment.split()
    if not tokens:
        return None
    title: str = tokens[0]
    items: list[str] = tokens[1:]
    if not items:
        return None
    return {"title": title, "items": items}


def parse_updates(text: str) -> list[dict[str, Any]]:
    """把 ``updates_info.txt`` 解析为分组条目。

    支持两种写法：

    - 结构化写法：``# 分类`` 标题配合 ``- 条目`` 列表；
    - 紧凑写法：``分类 条目1 条目2;分类2 条目3``，与需求文档示例一致。

    Args:
        text: 更新说明原文。

    Returns:
        分组列表，每项包含 ``title`` 与 ``items``。
    """
    source: str = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not source.strip():
        return []
    structured: bool = any(
        _HEADING_RE.match(line)
        or _BRACKET_HEADING_RE.match(line)
        or _BULLET_RE.match(line)
        or _COLON_GROUP_RE.match(line)
        for line in source.splitlines()
    )
    groups: list[dict[str, Any]] = []
    if not structured:
        for segment in re.split(r"[;\n]+", source):
            group: dict[str, Any] | None = _compact_group(segment.strip())
            if group is not None:
                groups.append(group)
        return groups

    current: dict[str, Any] | None = None
    for raw_line in source.splitlines():
        line: str = raw_line.strip()
        if not line:
            continue
        heading: re.Match[str] | None = (
            _HEADING_RE.match(line) or _BRACKET_HEADING_RE.match(line)
        )
        if heading:
            current = {"title": heading.group(1).strip(), "items": []}
            groups.append(current)
            continue
        bullet: re.Match[str] | None = _BULLET_RE.match(line)
        if bullet:
            if current is None:
                current = {"title": "更新内容", "items": []}
                groups.append(current)
            current["items"].append(bullet.group(1).strip())
            continue
        colon: re.Match[str] | None = _COLON_GROUP_RE.match(line)
        if colon:
            items: list[str] = [
                item.strip()
                for item in re.split(r"[;；]+", colon.group(2))
                if item.strip()
            ]
            current = {"title": colon.group(1).strip(), "items": items}
            groups.append(current)
            continue
        if current is None:
            current = {"title": line, "items": []}
            groups.append(current)
        else:
            current["items"].append(line)
    return [group for group in groups if group["title"] or group["items"]]


def load_updates() -> list[dict[str, Any]]:
    """读取并解析当前发行包的更新说明。

    Returns:
        分组列表；文件缺失时为空列表。
    """
    return parse_updates(_read_text(_UPDATES_FILE))


def welcome_payload() -> dict[str, Any]:
    """返回欢迎弹窗所需数据与是否应展示。

    Returns:
        含 ``show``、版本、标题、协议文本与更新分组的字典。
    """
    config: dict[str, Any] = load_config()
    ui: dict[str, Any] = config.get("ui") if isinstance(config.get("ui"), dict) else {}
    seen_version: str = str(ui.get("welcome_version", "") or "").strip()
    show: bool = seen_version != APP_VERSION
    if not show:
        return {
            "show": False,
            "version": APP_VERSION,
            "title": _WELCOME_TITLE % APP_VERSION,
            "subtitle": _WELCOME_SUBTITLE,
            "agreement_heading": _AGREEMENT_HEADING,
            "updates_heading": _UPDATES_HEADING % APP_VERSION,
            "agreement": "",
            "changelog": [],
        }
    return {
        "show": True,
        "version": APP_VERSION,
        "title": _WELCOME_TITLE % APP_VERSION,
        "subtitle": _WELCOME_SUBTITLE,
        "agreement_heading": _AGREEMENT_HEADING,
        "updates_heading": _UPDATES_HEADING % APP_VERSION,
        "agreement": load_agreement_text(),
        "changelog": load_updates(),
    }


def mark_welcome_seen(version: str = "") -> bool:
    """记录用户已确认当前版本的欢迎弹窗。

    Args:
        version: 前端回传的版本号；为空时使用当前版本，传入其他版本会被拒绝。

    Returns:
        记录成功返回 ``True``；版本不匹配或写入失败返回 ``False``。
    """
    target: str = str(version or "").strip() or APP_VERSION
    if target != APP_VERSION:
        _LOGGER.warning("拒绝记录非当前版本的欢迎弹窗: %s", target)
        return False
    try:
        update_config({"ui": {"welcome_version": APP_VERSION}})
    except OSError as exc:
        _LOGGER.warning("记录欢迎弹窗状态失败: %s", exc)
        return False
    return True
