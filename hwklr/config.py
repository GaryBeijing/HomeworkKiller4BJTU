# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-08 14:30
# 文件名: config.py
# 主要用途: 统一读写 config.json；按设置分组存放账号、密码、AI、构建与第三方扩展配置，并解析源码/虚拟环境/打包后的程序根目录。
# 文件版本: 4.0.0
"""项目配置读写。

配置文件固定位于**项目根目录**（``main.py`` 同级）的 ``config.json``。
所有模块都必须通过本模块访问配置，禁止各自拼路径或另存配置。
"""
from __future__ import annotations

import copy
import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any, Final

__version__ = "4.0.0"
__all__ = [
    "DEFAULT_CONFIG",
    "app_root",
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
        "enabled": True,
    },
    "c_programming": {
        "provider": "deepseek",
        "model": "deepseek-flash",
        "base_url": "https://api.deepseek.com",
        "api_key": "",
        "thinking_level": "auto",
        "max_concurrency": 1,
        "enable_solution_mode": False,
        "last_course_id": None,
        "enabled": True,
    },
    "icourse": {
        "account": "",
        "password": "",
        "account_type": "auto",
        "workers": 1,
        "video_rate": 2.0,
        "submit_quizzes": False,
        "publish_discussions": False,
        "answer_ttl_hours": 24,
        "auto_sync_answers": True,
        "download_documents": True,
        "enabled": True,
    },
    "build": {
        "output_dir": "",
        "dev_format": "executable",
        "plugin_template": "",
        "plugin_project": "",
        "enabled": True,
        "features": {
            "高铁纵横": "release",
            "C程序设计": "release",
            "中国大学慕课": "release",
            "构建": "dev",
        },
    },
    # 已启用的第三方扩展标签名（例如 ["我的插件"]）。
    "third-party": [],
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


def app_root() -> Path:
    """返回程序根目录。

    源码运行时是项目根目录；PyInstaller 打包后是可执行文件所在目录；
    V3 ``HwklrVenv`` 中通过 ``pyvenv.cfg`` 定位虚拟环境根目录。

    Returns:
        程序根目录的绝对路径。
    """
    if getattr(sys, "frozen", False):
        # 打包后 __file__ 位于 _internal 内，用户数据应放在 exe 旁边。
        return Path(sys.executable).resolve().parent
    # hwklr/config.py -> hwklr -> 项目根目录；V3 的 HwklrVenv 中 hwklr 位于 Lib/，
    # 此时继续向上找到含 pyvenv.cfg 的虚拟环境根目录。
    root: Path = Path(__file__).resolve().parent.parent
    for candidate in (root, root.parent):
        if (candidate / "pyvenv.cfg").is_file():
            return candidate
    return root


def config_path() -> Path:
    """返回配置文件路径。

    配置文件与数据库目录都位于 :func:`app_root`，避免源码、虚拟环境与
    打包布局下使用不同的路径规则。

    Returns:
        ``config.json`` 的绝对路径。
    """
    return app_root() / "config.json"


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
    hsr.setdefault("enabled", True)
    config["hsr"] = hsr

    # 步骤 2：补齐 C 程序设计分组的缺失字段。
    cprog: dict[str, Any] = (
        config.get("c_programming")
        if isinstance(config.get("c_programming"), dict)
        else {}
    )
    # 2.2.0 起删除温度设置，旧配置中的残留字段直接丢弃。
    cprog.pop("temperature", None)
    for key, value in DEFAULT_CONFIG["c_programming"].items():
        cprog.setdefault(key, copy.deepcopy(value))
    config["c_programming"] = cprog

    # 步骤 3：补齐构建分组；features 中缺失的功能默认标记为 release。
    build: dict[str, Any] = (
        config.get("build") if isinstance(config.get("build"), dict) else {}
    )
    for key, value in DEFAULT_CONFIG["build"].items():
        if key == "features":
            continue
        build.setdefault(key, copy.deepcopy(value))
    stored_features: Any = build.get("features")
    features: dict[str, Any] = (
        dict(stored_features) if isinstance(stored_features, dict) else {}
    )
    for name, state in DEFAULT_CONFIG["build"]["features"].items():
        features.setdefault(name, state)
    build["features"] = features
    config["build"] = build

    # 步骤 4：第三方扩展启用列表必须是字符串列表。
    third_party: Any = config.get("third-party")
    if isinstance(third_party, dict):
        config["third-party"] = [
            str(name) for name, state in third_party.items() if bool(state)
        ]
    elif isinstance(third_party, list):
        config["third-party"] = [str(item) for item in third_party if str(item).strip()]
    else:
        config["third-party"] = []
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
