# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-11 21:00
# 文件名: config.py
# 主要用途: 统一读写 config.json；按设置分组存放账号、密码、AI、构建与第三方扩展配置，并解析安装根目录与用户数据根目录。
# 文件版本: 4.5.0
"""项目配置读写。

配置文件固定位于**项目根目录**（``main.py`` 同级）的 ``config.json``。
所有模块都必须通过本模块访问配置，禁止各自拼路径或另存配置。
"""
from __future__ import annotations

import copy
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Final

from hwklr.feature_specs import (
    build_features_default,
    feature_config_defaults,
)

__version__ = "4.5.0"
__all__ = [
    "DEFAULT_CONFIG",
    "app_root",
    "config_path",
    "data_root",
    "install_root",
    "plugin_config_defaults",
    "load_config",
    "register_config_defaults",
    "save_config",
    "update_config",
]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
# 多个桥接线程可能同时保存配置；RLock 允许 load_config 缺文件时重入 save_config。
_CONFIG_LOCK = threading.RLock()
# 插件在加载时按 meta.config 注册的默认值；不回写 DEFAULT_CONFIG。
_PLUGIN_DEFAULTS: dict[str, dict[str, Any]] = {}
_PLUGIN_DEFAULTS_LOCK: Final[threading.Lock] = threading.Lock()


def register_config_defaults(section: str, defaults: dict[str, Any]) -> None:
    """登记插件配置板块的默认值。

    只影响后续 :func:`load_config` 的合并结果，不写入磁盘；用户配置始终
    优先于插件默认值。

    Args:
        section: 配置板块名。
        defaults: 默认值字典。
    """
    name: str = str(section or "").strip()
    if not name or not isinstance(defaults, dict):
        return
    with _PLUGIN_DEFAULTS_LOCK:
        bucket: dict[str, Any] = _PLUGIN_DEFAULTS.setdefault(name, {})
        for key, value in defaults.items():
            bucket.setdefault(str(key), copy.deepcopy(value))


def plugin_config_defaults() -> dict[str, dict[str, Any]]:
    """返回已登记插件默认值的深拷贝。

    Returns:
        板块名到默认值字典的映射。
    """
    with _PLUGIN_DEFAULTS_LOCK:
        return copy.deepcopy(_PLUGIN_DEFAULTS)

# 所有设置的默认值；新增设置项时在此追加，旧配置文件会自动补齐缺失字段。
CORE_DEFAULTS: Final[dict[str, Any]] = {
    "username": "",
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
    # 启动时是否检查并提示新版本；实际下载/安装仍由用户确认。
    "update_notice": True,
}


def _build_default_config() -> dict[str, Any]:
    """组合核心配置与各功能的 FeatureConfigSpec 默认值。"""
    feature_defaults: dict[str, dict[str, Any]] = feature_config_defaults()
    result: dict[str, Any] = {"username": CORE_DEFAULTS["username"]}
    for section, defaults in feature_defaults.items():
        result[str(section)] = dict(defaults)
    build_section: dict[str, Any] = result.setdefault("build", {})
    build_section["features"] = build_features_default()
    result["third-party"] = copy.deepcopy(CORE_DEFAULTS["third-party"])
    result["ui"] = copy.deepcopy(CORE_DEFAULTS["ui"])
    result["network"] = copy.deepcopy(CORE_DEFAULTS["network"])
    result["server"] = copy.deepcopy(CORE_DEFAULTS["server"])
    # 新增顶层键放在末尾，保持现有前五个键的顺序不变。
    result["update_notice"] = bool(CORE_DEFAULTS["update_notice"])
    return result


# 所有设置的默认值；新增功能应优先在 hwklr/feature_specs.py 声明。
DEFAULT_CONFIG: Final[dict[str, Any]] = _build_default_config()


def _defaults_with_plugins() -> dict[str, Any]:
    """返回包含运行期插件默认值的配置基准。

    Returns:
        默认配置深拷贝；插件默认值只补缺失键。
    """
    defaults: dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)
    for section, values in plugin_config_defaults().items():
        bucket: Any = defaults.get(section)
        if not isinstance(bucket, dict):
            bucket = {}
            defaults[section] = bucket
        for key, value in values.items():
            bucket.setdefault(key, value)
    return defaults


def _source_root() -> Path:
    """返回源码/虚拟环境布局下的项目根目录。"""
    # hwklr/config.py -> hwklr -> 项目根目录；V3 的 HwklrVenv 中 hwklr 位于 Lib/，
    # 此时继续向上找到含 pyvenv.cfg 的虚拟环境根目录。
    root: Path = Path(__file__).resolve().parent.parent
    for candidate in (root, root.parent):
        if (candidate / "pyvenv.cfg").is_file():
            return candidate
    return root


def install_root() -> Path:
    """返回安装根目录（launcher / versions / current.json 所在位置）。

    - launcher 与版本化程序通过 ``HWKLR_INSTALL_ROOT`` 显式传入；
    - 打包后若可执行文件位于 ``launcher/`` 或 ``versions/<v>/``，自动上溯；
    - 其它打包布局回退到 exe 同级；
    - 源码运行回退到项目根目录。
    """
    env_value: str = str(os.environ.get("HWKLR_INSTALL_ROOT") or "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    if getattr(sys, "frozen", False):
        executable: Path = Path(sys.executable).resolve()
        # Windows: <root>/launcher/App.exe 或 <root>/versions/<v>/App.exe
        # macOS: <root>/launcher/App.app/Contents/MacOS/App 或
        #        <root>/versions/<v>/App.app/Contents/MacOS/App
        for parent in executable.parents:
            if parent.name == "launcher":
                return parent.parent
            if parent.name == "versions":
                return parent.parent
        return executable.parent
    return _source_root()


def data_root() -> Path:
    """返回用户数据根目录（config/db/auth/documents/artifacts 等）。

    优先级：
    1. ``HWKLR_DATA_ROOT`` 环境变量；
    2. ``--data-root <path>`` 命令行参数；
    3. macOS 打包后 ``~/Library/Application Support/HomeworkKiller4BJTU``；
    4. Windows/源码：安装根目录（保持现有用户数据位置）。
    """
    env_value: str = str(os.environ.get("HWKLR_DATA_ROOT") or "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    argv: list[str] = list(getattr(sys, "argv", []))
    for index, argument in enumerate(argv):
        if argument == "--data-root" and index + 1 < len(argv):
            return Path(argv[index + 1]).expanduser().resolve()
        if argument.startswith("--data-root="):
            return Path(argument.split("=", 1)[1]).expanduser().resolve()
    if getattr(sys, "frozen", False) and sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "HomeworkKiller4BJTU"
        )
    return install_root()


def app_root() -> Path:
    """兼容旧代码：返回用户数据根目录。"""
    return data_root()


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
        default_config: dict[str, Any] = _defaults_with_plugins()
        save_config(default_config)
        return default_config

    try:
        with path.open(encoding="utf-8-sig") as fp:
            loaded: Any = json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        _LOGGER.warning("读取配置文件失败，将使用默认配置: %s", exc)
        return _defaults_with_plugins()

    if not isinstance(loaded, dict):
        _LOGGER.warning("配置文件内容不是对象，将使用默认配置。")
        return _defaults_with_plugins()
    # 插件默认值只补缺失键，不覆盖核心/官方默认值，也不覆盖用户配置。
    return _migrate_config(_deep_merge(_defaults_with_plugins(), loaded))


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
    with _CONFIG_LOCK:
        current: dict[str, Any] = load_config()
        updated: dict[str, Any] = _deep_merge(current, patch)
        save_config(updated)
        return updated
