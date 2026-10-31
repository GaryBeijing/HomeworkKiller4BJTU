# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-01 00:01
# 文件名: config.py
# 主要用途: 统一读写项目根目录 config.json；V2 起按设置分组存放账号、高铁密码与 C 程序设计 AI 配置。
# 文件版本: 2.0.0
"""项目配置读写。

配置文件固定位于**项目根目录**（``main.py`` 同级）的 ``config.json``。
所有模块都必须通过本模块访问配置，禁止各自拼路径或另存配置。
"""
from __future__ import annotations

import copy
import json
import logging
import threading
from pathlib import Path
from typing import Any, Final

__version__ = "1.0.0"
__all__ = [
    "DEFAULT_CONFIG",
    "config_path",
    "load_config",
    "save_config",
    "update_config",
]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
# 多个桥接线程可能同时保存配置，用锁避免临时文件互相覆盖。
_CONFIG_LOCK: Final[threading.Lock] = threading.Lock()

# 所有设置的默认值；新增设置项时在此追加，旧配置文件会自动补齐缺失字段。
DEFAULT_CONFIG: Final[dict[str, Any]] = {
    "username": "",
    "hsr": {
        "password": "",
    },
    "c_programming": {
        "provider": "deepseek",
        "model": "deepseek-flash",
        "base_url": "https://api.deepseek.com",
        "api_key": "",
        "temperature": 0.3,
        "enable_solution_mode": False,
        "last_course_id": None,
    },
    "ui": {
        "width": 1100,
        "height": 720,
        "min_width": 900,
        "min_height": 620,
        "debug": False,
    },
    "network": {
        "timeout_seconds": 40,
    },
    "server": {
        "preferred_port": 49152,
    },
}


def config_path() -> Path:
    """返回配置文件路径。

    Returns:
        项目根目录下 ``config.json`` 的绝对路径。
    """
    # hwklr/config.py -> hwklr -> 项目根目录
    return Path(__file__).resolve().parent.parent / "config.json"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并两个字典，``override`` 优先，且不修改入参。

    Args:
        base: 默认配置（基准）。
        override: 用户配置（优先）。

    Returns:
        合并后的新字典。
    """
    merged: dict[str, Any] = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_config() -> dict[str, Any]:
    """读取配置并与默认值合并。

    文件不存在时会自动创建一份默认配置；文件损坏时记录警告并返回默认值
    （不覆盖损坏文件，避免用户设置被静默清空）。

    Returns:
        合并后的完整配置字典。
    """
    path: Path = config_path()
    if not path.exists():
        default_config: dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)
        save_config(default_config)
        return default_config

    try:
        with path.open(encoding="utf-8-sig") as fp:
            loaded: Any = json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        _LOGGER.warning("读取配置文件失败，将使用默认配置: %s", exc)
        return copy.deepcopy(DEFAULT_CONFIG)

    if not isinstance(loaded, dict):
        _LOGGER.warning("配置文件内容不是对象，将使用默认配置。")
        return copy.deepcopy(DEFAULT_CONFIG)
    return _migrate_config(_deep_merge(DEFAULT_CONFIG, loaded))


def _migrate_config(config: dict[str, Any]) -> dict[str, Any]:
    """把旧版配置迁移到 V2 的分组结构。

    V1 的密码直接放在顶层 ``password``；V2 改为 ``hsr.password``。
    迁移只在内存中进行，下一次保存时写回新结构。

    Args:
        config: 已与默认值合并的配置。

    Returns:
        迁移后的配置字典。
    """
    # 步骤 1：把顶层 password 迁移到高铁纵横分组。
    hsr: dict[str, Any] = config.get("hsr") if isinstance(config.get("hsr"), dict) else {}
    legacy_password: Any = config.pop("password", "")
    if not hsr.get("password") and legacy_password:
        hsr["password"] = str(legacy_password)
    hsr.setdefault("password", "")
    config["hsr"] = hsr

    # 步骤 2：补齐 C 程序设计分组的缺失字段。
    cprog: dict[str, Any] = (
        config.get("c_programming")
        if isinstance(config.get("c_programming"), dict)
        else {}
    )
    for key, value in DEFAULT_CONFIG["c_programming"].items():
        cprog.setdefault(key, copy.deepcopy(value))
    config["c_programming"] = cprog
    return config


def save_config(config: dict[str, Any]) -> None:
    """原子写入配置文件。

    Args:
        config: 要持久化的完整配置字典。

    Raises:
        OSError: 无法创建目录或写入临时文件时抛出。
    """
    path: Path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path = path.with_suffix(".json.tmp")
    # 先写临时文件再替换，避免写入中断导致配置损坏。
    with _CONFIG_LOCK:
        with temp_path.open("w", encoding="utf-8") as fp:
            json.dump(config, fp, ensure_ascii=False, indent=2)
            fp.write("\n")
        temp_path.replace(path)


def update_config(patch: dict[str, Any]) -> dict[str, Any]:
    """按补丁更新配置并持久化。

    Args:
        patch: 需要写入的配置片段，允许只包含部分字段。

    Returns:
        更新后的完整配置字典。
    """
    current: dict[str, Any] = load_config()
    updated: dict[str, Any] = _deep_merge(current, patch)
    save_config(updated)
    return updated
