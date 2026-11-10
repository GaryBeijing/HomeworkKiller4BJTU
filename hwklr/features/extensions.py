# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-03 17:20
# 最后更新: 2026-11-10 23:59
# 文件名: extensions.py
# 主要用途: 第三方扩展的扫描、校验、导入、启用状态管理，以及插件工程模板与插件发布包构建。
# 文件版本: 4.4.2
"""第三方扩展与插件工程支持。

扩展目录结构（zip 解压后）：::

    extension/
    └── {作者}-{扩展名}-{vA.BpC-bD}/
        ├── meta.json
        ├── feature/
        │   └── __init__.py
        └── UI/
            ├── index.html
            ├── css/
            └── js/

本模块只负责“扩展资产”的读写与校验；把扩展注册成标签页由
:class:`hwklr.UI.WindowView` 完成。
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from hwklr.config import load_config, register_config_defaults, update_config
from hwklr.feature_specs import (
    FeatureAssetSpec,
    FeatureConfigSpec,
    FeatureDbSpec,
    FeaturePackagingSpec,
    official_sections,
)
from hwklr.features.base import Feature
from hwklr.features.versions import format_plugin_version

__version__ = "4.4.2"
__author__ = "Gary"
__all__ = [
    "ExtensionError",
    "ExtensionInfo",
    "PluginSpec",
    "app_home",
    "build_plugin_package",
    "bundled_template_zip",
    "create_plugin_project",
    "extension_root",
    "get_extensions_payload",
    "install_extension_git",
    "install_extension_zip",
    "invalidate_extension_cache",
    "is_feature_enabled",
    "load_extension_dir",
    "parse_plugin_spec",
    "project_extension_root",
    "read_project_metadata",
    "scan_installed_extensions",
    "set_extension_enabled",
    "set_feature_enabled",
    "venv_root",
]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_SAFE_NAME: Final[re.Pattern[str]] = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_PACKAGE_NAME: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_GIT_TIMEOUT: Final[int] = 300
_MODULE_SEQ: int = 0
_SCAN_LOCK: Final[threading.RLock] = threading.RLock()
_SCAN_CACHE: tuple[
    tuple["ExtensionInfo", ...],
    tuple[str, ...],
    tuple[tuple[str, int], ...],
] | None = None
# 官方功能名/稳定 id -> config 中保存启用状态的板块键。
_OFFICIAL_SECTIONS: Final[dict[str, str]] = official_sections()


class ExtensionError(RuntimeError):
    """扩展导入/校验失败时抛出的可读异常。"""


@dataclass(frozen=True)
class PluginSpec:
    """插件 ``meta.json`` 的规范化声明。

    所有字段均为可选；未声明的字段回退到 3.0.0 的 7 键 manifest 行为。
    """

    schema: int = 1
    id: str = ""
    order: int = 0
    update_date: str = ""
    ui: FeatureAssetSpec | None = None
    assets: FeatureAssetSpec | None = None
    actions: tuple[dict[str, Any], ...] = ()
    config: FeatureConfigSpec | None = None
    db: FeatureDbSpec | None = None
    packaging: FeaturePackagingSpec = field(default_factory=FeaturePackagingSpec)
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True)
class ExtensionInfo:
    """一个可用扩展的静态描述。"""

    id: str
    """扩展目录名，同时作为资源 URL 的标识。"""

    path: Path
    """扩展根目录。"""

    tab_name: str
    """标签页显示名称（功能名）。"""

    package: str
    """插件包名。"""

    author: str
    """插件作者。"""

    version: str
    """插件原始版本号。"""

    update_date: str
    """更新日期。"""

    official: bool
    """是否为官方插件。"""

    feature_cls: type[Feature]
    """扩展入口功能类。"""

    description: str = ""
    """标签说明。"""

    css_files: tuple[str, ...] = ()
    """相对扩展根目录的 CSS 文件。"""

    js_files: tuple[str, ...] = ()
    """相对扩展根目录的 JS 文件。"""

    spec: PluginSpec = field(default_factory=PluginSpec)
    """规范化后的插件声明。"""

    db_provider: Any = None
    """按 ``meta.db`` 实例化的数据库 provider；未声明时为 ``None``。"""

    @property
    def schema(self) -> int:
        """返回 manifest schema 版本。"""
        return int(self.spec.schema)

    @property
    def plugin_id(self) -> str:
        """返回插件声明的稳定 id；未声明时使用扩展目录名。"""
        return self.spec.id or self.id

    @property
    def order(self) -> int:
        """返回标签排序值；未声明时为 0。"""
        return int(self.spec.order)

    @property
    def actions(self) -> tuple[dict[str, Any], ...]:
        """返回 manifest 中声明的动作元数据。"""
        return self.spec.actions

    @property
    def assets(self) -> FeatureAssetSpec | None:
        """返回 UI 资源声明。"""
        return self.spec.assets or self.spec.ui

    @property
    def version_display(self) -> str:
        """返回插件展示版本号。

        Returns:
            ``A.BpC-bD`` 形式。
        """
        return format_plugin_version(self.version)

    def payload(self, enabled: bool) -> dict[str, Any]:
        """返回供 UI 渲染的扩展信息。

        Args:
            enabled: 当前是否启用。

        Returns:
            可 JSON 序列化的字典。
        """
        return {
            "id": self.id,
            "name": self.tab_name,
            "package": self.package,
            "author": self.author,
            "version": self.version,
            "version_display": self.version_display,
            "update_date": self.update_date,
            "official": self.official,
            "enabled": bool(enabled),
            "path": str(self.path),
            "description": self.description,
            "schema": self.schema,
            "plugin_id": self.plugin_id,
            "order": self.order,
            "actions": [dict(item) for item in self.actions],
            "config_section": (
                self.spec.config.section if self.spec.config is not None else ""
            ),
            "database": (
                self.spec.db.base_name if self.spec.db is not None else ""
            ),
            "has_ui_override": bool(self.assets is not None),
        }


def app_home() -> Path:
    """返回程序所在目录（扩展目录与虚拟环境放在这里）。

    兼容三种布局：源码仓库（根目录即 venv）、开发虚拟环境（``hwklr`` 位于
    ``Lib/``）、python-embed 开发包（``start.bat`` 位于 ``app/`` 的上级）。

    Returns:
        程序主目录。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    project_root: Path = Path(__file__).resolve().parents[2]
    # 源码仓库 / HwklrVenv：含 pyvenv.cfg 与 main.py 的目录。
    for candidate in (project_root, project_root.parent):
        if (candidate / "pyvenv.cfg").is_file() and (
            candidate / "main.py"
        ).is_file():
            return candidate
    # 开发包：start.bat / BUILD_INFO.json 所在的目录才是程序根目录。
    for candidate in (project_root, project_root.parent, project_root.parent.parent):
        if (candidate / "start.bat").is_file() or (
            candidate / "BUILD_INFO.json"
        ).is_file():
            return candidate
    return project_root


def extension_root() -> Path:
    """返回已安装扩展的根目录。

    Returns:
        ``app_home()/extension``。
    """
    return app_home() / "extension"


def venv_root() -> Path:
    """返回开发虚拟环境目录。

    源码运行时项目根目录本身就是虚拟环境（存在 ``pyvenv.cfg``），直接复用；
    开发产物中则在程序目录旁创建 ``HwklrVenv``。

    Returns:
        虚拟环境根目录。
    """
    home: Path = app_home()
    if (home / "pyvenv.cfg").is_file():
        return home
    return home / "HwklrVenv"


def project_extension_root() -> Path:
    """返回开发虚拟环境中存放插件工程样例的目录。

    Returns:
        ``HwklrVenv/extension``。
    """
    return venv_root() / "extension"


def bundled_template_zip() -> Path | None:
    """查找随程序分发的插件工程模板 zip。

    Returns:
        模板 zip；未找到时返回 ``None``。
    """
    candidates: tuple[Path, ...] = (
        Path(__file__).resolve().parent / "build" / "vendor" / "plugin-template.zip",
        app_home() / "vendor" / "plugin-template.zip",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _safe_component(value: str, fallback: str = "extension") -> str:
    """把任意文本转换为 Windows 可用的目录/文件名片段。

    Args:
        value: 原始文本。
        fallback: 文本为空时的兜底值。

    Returns:
        安全片段。
    """
    cleaned: str = _SAFE_NAME.sub("_", str(value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = fallback
    return cleaned[:80].strip(" .") or fallback


def _config_enabled_names() -> list[str]:
    """读取 config.json 中启用的扩展标签名列表。

    Returns:
        启用的扩展标签名。
    """
    config: dict[str, Any] = load_config()
    value: Any = config.get("third-party")
    if isinstance(value, dict):
        return [str(name) for name, state in value.items() if bool(state)]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _save_enabled_names(names: list[str]) -> None:
    """把启用的扩展标签名写回 config.json。

    Args:
        names: 启用列表（会去重并保持顺序）。
    """
    unique: list[str] = []
    for name in names:
        text: str = str(name or "").strip()
        if text and text not in unique:
            unique.append(text)
    update_config({"third-party": unique})


def is_extension_enabled(name: str) -> bool:
    """判断扩展是否启用。

    Args:
        name: 扩展标签名。

    Returns:
        已启用返回 ``True``。
    """
    return str(name or "") in _config_enabled_names()


def is_feature_enabled(name: str) -> bool:
    """判断功能是否启用（官方功能或第三方扩展）。

    Args:
        name: 功能标签名。

    Returns:
        启用返回 ``True``。
    """
    section: str | None = _OFFICIAL_SECTIONS.get(str(name or ""))
    if section is not None:
        config: dict[str, Any] = load_config()
        group: Any = config.get(section)
        if isinstance(group, dict):
            return bool(group.get("enabled", True))
        return True
    return is_extension_enabled(name)


def set_extension_enabled(name: str, enabled: bool) -> None:
    """设置扩展启用状态。

    Args:
        name: 扩展标签名。
        enabled: 是否启用。
    """
    names: list[str] = _config_enabled_names()
    target: str = str(name or "").strip()
    if not target:
        return
    if enabled and target not in names:
        names.append(target)
    if not enabled:
        names = [item for item in names if item != target]
    _save_enabled_names(names)


def set_feature_enabled(name: str, enabled: bool) -> None:
    """设置功能启用状态。

    Args:
        name: 功能标签名。
        enabled: 是否启用。
    """
    section: str | None = _OFFICIAL_SECTIONS.get(str(name or ""))
    if section is not None:
        update_config({section: {"enabled": bool(enabled)}})
        return
    set_extension_enabled(name, enabled)


def _read_json(path: Path) -> dict[str, Any]:
    """读取 JSON 对象。

    Args:
        path: 文件路径。

    Returns:
        解析后的字典；格式不符时返回空字典。
    """
    try:
        with path.open(encoding="utf-8-sig") as fp:
            value: Any = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _project_base(path: Path) -> Path:
    """定位包含 ``meta.json`` / ``feature`` 的工程根目录。

    Args:
        path: 用户选择或解压得到的目录。

    Returns:
        工程根目录；无法判断时原样返回。
    """
    if (path / "meta.json").is_file() or (path / "feature" / "__init__.py").is_file():
        return path
    if not path.is_dir():
        return path
    children: list[Path] = [child for child in path.iterdir() if child.is_dir()]
    if len(children) == 1:
        return children[0]
    return path


def _ast_str(node: ast.AST | None) -> str:
    """从 AST 常量节点读取字符串。

    Args:
        node: AST 节点。

    Returns:
        字符串；不是常量字符串时返回空串。
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _relative_asset(value: Any, field_name: str) -> str:
    """校验并规范化插件内的相对资源路径。

    Args:
        value: 原始路径。
        field_name: 出错时展示的字段名。

    Returns:
        POSIX 风格的相对路径；空值返回空串。

    Raises:
        ExtensionError: 路径为绝对路径或包含 ``..``。
    """
    text: str = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    parts: list[str] = [part for part in text.split("/") if part not in ("", ".")]
    if text.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
        raise ExtensionError("%s 必须是插件目录内的相对路径：%s" % (field_name, text))
    return "/".join(parts)


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    """把字符串/列表规范化为相对路径元组。

    Args:
        value: 原始值。
        field_name: 出错时展示的字段名。

    Returns:
        去空后的相对路径元组。
    """
    raw_items: list[Any] = [value] if isinstance(value, str) else (
        list(value) if isinstance(value, (list, tuple)) else []
    )
    result: list[str] = []
    for item in raw_items:
        path: str = _relative_asset(item, field_name)
        if path:
            result.append(path)
    return tuple(result)


def _asset_spec(value: Any, field_name: str) -> FeatureAssetSpec | None:
    """解析 ``ui`` / ``assets`` 声明。

    Args:
        value: manifest 中的对象。
        field_name: 出错时展示的字段名。

    Returns:
        资源声明；对象为空时返回 ``None``。
    """
    if not isinstance(value, dict):
        return None
    html: str = _relative_asset(
        value.get("html") or value.get("index") or "", field_name + ".html"
    )
    css: tuple[str, ...] = _string_tuple(value.get("css"), field_name + ".css")
    js: tuple[str, ...] = _string_tuple(value.get("js"), field_name + ".js")
    runtime_dirs: tuple[str, ...] = _string_tuple(
        value.get("runtime_dirs"), field_name + ".runtime_dirs"
    )
    if not (html or css or js or runtime_dirs):
        return None
    return FeatureAssetSpec(
        html=html,
        css=css,
        js=js,
        runtime_dirs=runtime_dirs,
    )


def _action_specs(value: Any) -> tuple[dict[str, Any], ...]:
    """解析插件声明的动作元数据。

    Args:
        value: manifest 中的 ``actions``。

    Returns:
        规范化动作列表；非法条目不参与校验，只保留可读字段。
    """
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            name: str = item.strip()
            payload: dict[str, Any] = {"name": name}
        elif isinstance(item, dict):
            payload = dict(item)
            name = str(payload.get("name") or "").strip()
        else:
            continue
        if not name:
            continue
        payload["name"] = name
        payload.setdefault("description", "")
        payload.setdefault("risk", "read")
        params: Any = payload.get("params")
        payload["params"] = list(params) if isinstance(params, (list, tuple)) else []
        result.append(payload)
    return tuple(result)


def _config_spec(value: Any) -> FeatureConfigSpec | None:
    """解析插件配置声明。

    Args:
        value: manifest 中的 ``config``。

    Returns:
        配置声明；缺少 section 时返回 ``None``。
    """
    if not isinstance(value, dict):
        return None
    section: str = str(value.get("section") or value.get("name") or "").strip()
    if not section:
        return None
    raw_defaults: Any = value.get("defaults")
    defaults: tuple[tuple[str, Any], ...] = ()
    if isinstance(raw_defaults, dict):
        defaults = tuple((str(key), item) for key, item in raw_defaults.items())
    legacy: tuple[str, ...] = tuple(
        str(item) for item in value.get("legacy_sections", [])
        if str(item).strip()
    )
    return FeatureConfigSpec(
        section=section,
        defaults=defaults,
        legacy_sections=legacy,
    )


def _db_spec(value: Any, fallback_name: str) -> FeatureDbSpec | None:
    """解析插件数据库声明。

    Args:
        value: manifest 中的 ``db`` / ``database``。
        fallback_name: 未声明 base_name 时使用的名称。

    Returns:
        数据库声明；缺少 provider 类时返回 ``None``。
    """
    if not isinstance(value, dict):
        return None
    provider_module: str = str(
        value.get("provider_module") or value.get("module") or ""
    ).strip()
    provider_class: str = str(
        value.get("provider_class") or value.get("class") or ""
    ).strip()
    if not provider_module or not provider_class:
        return None
    return FeatureDbSpec(
        base_name=str(value.get("base_name") or value.get("name") or fallback_name),
        provider_module=provider_module,
        provider_class=provider_class,
        source_files=_string_tuple(value.get("source_files"), "db.source_files"),
        provider_modules=_string_tuple(
            value.get("provider_modules"), "db.provider_modules"
        ),
        runtime_asset_prefixes=_string_tuple(
            value.get("runtime_asset_prefixes"), "db.runtime_asset_prefixes"
        ),
        excluded_paths=_string_tuple(
            value.get("excluded_paths"), "db.excluded_paths"
        ),
    )


def _packaging_spec(value: Any) -> FeaturePackagingSpec:
    """解析插件打包声明。

    Args:
        value: manifest 中的 ``packaging``。

    Returns:
        打包声明；缺失字段使用默认值。
    """
    if not isinstance(value, dict):
        return FeaturePackagingSpec()
    return FeaturePackagingSpec(
        hidden_imports=_string_tuple(
            value.get("hidden_imports"), "packaging.hidden_imports"
        ),
        collect_submodules=_string_tuple(
            value.get("collect_submodules"), "packaging.collect_submodules"
        ),
        collect_all=_string_tuple(value.get("collect_all"), "packaging.collect_all"),
        extra_modules=_string_tuple(
            value.get("extra_modules"), "packaging.extra_modules"
        ),
        extra_excludes=_string_tuple(
            value.get("extra_excludes"), "packaging.extra_excludes"
        ),
        dev_default=str(value.get("dev_default") or "release"),
        always_dev=bool(value.get("always_dev")),
        plugin_template=str(value.get("plugin_template") or ""),
    )


def parse_plugin_spec(meta: dict[str, Any], fallback_id: str = "") -> PluginSpec:
    """把插件 ``meta.json`` 解析为 :class:`PluginSpec`。

    所有新字段都是可选的；旧 7 键 manifest 解析后只得到 schema=1 与原始
    ``raw``，不改变既有加载行为。

    Args:
        meta: 已读取的 meta 对象。
        fallback_id: 未声明 id 时使用的扩展目录名。

    Returns:
        规范化插件声明。

    Raises:
        ExtensionError: 资源路径越过插件目录，或字段类型明显错误。
    """
    raw: dict[str, Any] = dict(meta) if isinstance(meta, dict) else {}
    try:
        schema: int = int(raw.get("schema") or 1)
    except (TypeError, ValueError):
        schema = 1
    try:
        order: int = int(raw.get("order") or 0)
    except (TypeError, ValueError):
        order = 0
    ui: FeatureAssetSpec | None = _asset_spec(raw.get("ui"), "ui")
    assets: FeatureAssetSpec | None = _asset_spec(raw.get("assets"), "assets")
    plugin_id: str = str(raw.get("id") or fallback_id or "").strip()
    db: FeatureDbSpec | None = _db_spec(
        raw.get("db") if "db" in raw else raw.get("database"),
        plugin_id or fallback_id,
    )
    return PluginSpec(
        schema=max(1, schema),
        id=plugin_id,
        order=order,
        update_date=str(raw.get("update_date") or raw.get("date") or ""),
        ui=ui,
        assets=assets,
        actions=_action_specs(raw.get("actions")),
        config=_config_spec(raw.get("config")),
        db=db,
        packaging=_packaging_spec(raw.get("packaging")),
        raw=raw,
    )


def read_project_metadata(project_dir: Path) -> dict[str, Any]:
    """读取插件工程的结构与元信息（不执行插件代码）。

    Args:
        project_dir: 插件工程根目录。

    Returns:
        含 ``name``、``package``、``author``、``version``、``update_date``、
        ``official``、``tab_name``、``feature_file``、``ui_dir`` 的字典。

    Raises:
        ExtensionError: 目录结构不完整时抛出。
    """
    base: Path = _project_base(Path(project_dir))
    feature_file: Path = base / "feature" / "__init__.py"
    ui_dir: Path = base / "UI"
    if not feature_file.is_file():
        raise ExtensionError("缺少 feature/__init__.py")
    meta: dict[str, Any] = _read_json(base / "meta.json")
    spec: PluginSpec = parse_plugin_spec(meta, base.name)
    html_path: str = (
        spec.assets.html if spec.assets is not None and spec.assets.html
        else (spec.ui.html if spec.ui is not None and spec.ui.html else "UI/index.html")
    )
    if not (base / html_path).is_file():
        raise ExtensionError("缺少 UI 入口：%s" % html_path)
    try:
        tree: ast.Module = ast.parse(feature_file.read_text(encoding="utf-8-sig"))
    except (OSError, SyntaxError) as exc:
        raise ExtensionError("无法读取 feature/__init__.py：%s" % exc) from exc

    values: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        values["__all__"] = [
                            _ast_str(item) for item in node.value.elts if _ast_str(item)
                        ]
                elif target.id.startswith("__"):
                    text: str = _ast_str(node.value)
                    if text:
                        values[target.id] = text
    all_names: list[str] = list(values.get("__all__") or [])
    if len(all_names) != 1:
        raise ExtensionError("__all__ 中应恰好包含一个 Feature 类名")
    name: str = str(
        values.get("__feature_name__")
        or meta.get("name")
        or meta.get("extension_name")
        or base.name
    )
    package: str = str(
        values.get("__package_name__") or meta.get("package") or base.name
    )
    author: str = str(values.get("__author__") or meta.get("author") or "Unknown")
    version: str = str(values.get("__version__") or meta.get("version") or "0.0.0")
    update_date: str = str(
        values.get("__update_date__")
        or meta.get("update_date")
        or meta.get("date")
        or ""
    )
    official_raw: Any = values.get("__official__", meta.get("official", False))
    official: bool = (
        official_raw
        if isinstance(official_raw, bool)
        else str(official_raw).strip().lower() in {"1", "true", "yes", "on", "是"}
    )
    return {
        "base": base,
        "feature_file": feature_file,
        "ui_dir": ui_dir,
        "meta": meta,
        "spec": spec,
        "name": name,
        "tab_name": name,
        "package": package,
        "author": author,
        "version": version,
        "update_date": update_date,
        "official": official,
        "feature_class_name": all_names[0],
        "description": str(meta.get("description") or ""),
    }


def _module_name(identifier: str) -> str:
    """生成唯一的扩展模块名。

    Args:
        identifier: 目录名或包名。

    Returns:
        合法的模块名。
    """
    global _MODULE_SEQ
    _MODULE_SEQ += 1
    safe_id: str = re.sub(r"[^A-Za-z0-9_]", "_", identifier or "extension")
    return "hwklr_extension_%s_%d_%d" % (safe_id, int(time.time() * 1000), _MODULE_SEQ)


def _load_module(feature_dir: Path, module_name: str) -> Any:
    """从任意目录加载扩展入口模块。

    Args:
        feature_dir: ``feature`` 目录。
        module_name: 唯一模块名。

    Returns:
        已执行的模块对象。

    Raises:
        ExtensionError: 模块导入失败时抛出。
    """
    init_file: Path = feature_dir / "__init__.py"
    inserted: bool = False
    sys_path: str = str(feature_dir)
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
        inserted = True
    try:
        spec: importlib.util.ModuleSpec | None = importlib.util.spec_from_file_location(
            module_name,
            init_file,
            submodule_search_locations=[str(feature_dir)],
        )
        if spec is None or spec.loader is None:
            raise ExtensionError("无法创建插件模块加载器")
        module: Any = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise ExtensionError("插件代码加载失败：%s" % exc) from exc
    finally:
        if inserted:
            try:
                sys.path.remove(sys_path)
            except ValueError:
                pass


def _discover_assets(
    base: Path,
    declared: FeatureAssetSpec | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """发现扩展 UI 下的 CSS/JS 文件。

    Args:
        base: 扩展根目录。
        declared: manifest 中显式声明的资源；存在时完全取代目录约定。

    Returns:
        ``(css 相对路径, js 相对路径)``，均相对扩展根目录。
    """
    if declared is not None and (declared.css or declared.js):
        return declared.css, declared.js
    css_files: list[str] = []
    js_files: list[str] = []
    for sub, bucket in (("UI/css", css_files), ("UI/js", js_files)):
        directory: Path = base / sub
        if not directory.is_dir():
            continue
        for file_path in sorted(directory.rglob("*")):
            if file_path.is_file() and file_path.suffix.lower() in (
                {".css"} if sub.endswith("css") else {".js"}
            ):
                bucket.append(file_path.relative_to(base).as_posix())
    return tuple(css_files), tuple(js_files)


def _load_plugin_db_provider(base: Path, spec: FeatureDbSpec | None) -> Any:
    """按插件声明的数据库路径实例化 provider。

    Args:
        base: 扩展根目录。
        spec: 数据库声明。

    Returns:
        provider 实例；未声明或加载失败时返回 ``None``。
    """
    if spec is None:
        return None
    search_dirs: tuple[Path, ...] = (base / "feature", base)
    inserted: list[str] = []
    try:
        for directory in search_dirs:
            text: str = str(directory)
            if directory.is_dir() and text not in sys.path:
                sys.path.insert(0, text)
                inserted.append(text)
        # 不同插件可能声明同名 provider 模块；先移除缓存，避免加载到上一个插件。
        sys.modules.pop(spec.provider_module, None)
        module: Any = importlib.import_module(spec.provider_module)
        provider_cls: Any = getattr(module, spec.provider_class)
        parameters = inspect.signature(provider_cls).parameters
        if "base_name" in parameters:
            return provider_cls(base_name=spec.base_name)
        return provider_cls()
    except Exception as exc:
        _LOGGER.warning(
            "插件数据库 provider 加载失败 %s.%s: %s",
            spec.provider_module,
            spec.provider_class,
            exc,
        )
        return None
    finally:
        for text in inserted:
            try:
                sys.path.remove(text)
            except ValueError:
                pass


def load_extension_dir(project_dir: Path, *, validate: bool = True) -> ExtensionInfo:
    """加载并校验一个扩展目录。

    Args:
        project_dir: 扩展根目录。
        validate: 是否检查 ``UI/index.html`` 等结构。

    Returns:
        扩展信息。

    Raises:
        ExtensionError: 结构、元信息或 Feature 基类校验失败时抛出。
    """
    metadata: dict[str, Any] = read_project_metadata(project_dir)
    base: Path = Path(metadata["base"]).resolve()
    spec: PluginSpec = metadata.get("spec") or PluginSpec()
    if validate:
        declared: FeatureAssetSpec | None = spec.assets or spec.ui
        html: str = (
            declared.html if declared is not None and declared.html
            else "UI/index.html"
        )
        if not (base / html).is_file():
            raise ExtensionError("缺少 UI 入口：%s" % html)
        for asset in (
            *(declared.css if declared is not None else ()),
            *(declared.js if declared is not None else ()),
        ):
            if not (base / asset).is_file():
                raise ExtensionError("缺少 UI 资源：%s" % asset)
    module: Any = _load_module(base / "feature", _module_name(base.name))
    all_names: Any = getattr(module, "__all__", None)
    if not isinstance(all_names, (list, tuple)) or len(all_names) != 1:
        raise ExtensionError("__all__ 中应恰好包含一个 Feature 类名")
    class_name: str = str(all_names[0])
    feature_cls: Any = getattr(module, class_name, None)
    if not isinstance(feature_cls, type) or not issubclass(feature_cls, Feature):
        raise ExtensionError("__all__ 中的 %s 不是 Feature 子类" % class_name)
    # #尝试实例化一次，确认插件能真正加载（缺少抽象属性、初始化异常都能提前暴露）。
    try:
        feature_cls({"context": {"port": 0}, "app_meta": {}})
    except Exception as exc:
        raise ExtensionError("插件初始化失败：%s" % exc) from exc
    css_files, js_files = _discover_assets(base, spec.assets or spec.ui)
    meta: dict[str, Any] = metadata["meta"]
    if spec.config is not None:
        register_config_defaults(spec.config.section, dict(spec.config.defaults))
    db_provider: Any = _load_plugin_db_provider(base, spec.db)
    return ExtensionInfo(
        id=base.name,
        path=base,
        tab_name=str(getattr(module, "__feature_name__", "") or metadata["tab_name"]),
        package=str(
            getattr(module, "__package_name__", "") or metadata["package"]
        ),
        author=str(getattr(module, "__author__", "") or metadata["author"]),
        version=str(getattr(module, "__version__", "") or metadata["version"]),
        update_date=str(
            getattr(module, "__update_date__", "") or metadata["update_date"]
        ),
        official=bool(
            getattr(module, "__official__", metadata["official"])
            if isinstance(getattr(module, "__official__", metadata["official"]), bool)
            else metadata["official"]
        ),
        feature_cls=feature_cls,
        description=str(meta.get("description") or ""),
        css_files=css_files,
        js_files=js_files,
        spec=spec,
        db_provider=db_provider,
    )


def invalidate_extension_cache() -> None:
    """清空已安装扩展扫描缓存。"""
    global _SCAN_CACHE
    with _SCAN_LOCK:
        _SCAN_CACHE = None


def _extension_signature(root: Path) -> tuple[tuple[str, int], ...]:
    """计算扩展目录签名，用于判断缓存是否失效。

    Args:
        root: ``extension/`` 根目录。

    Returns:
        排序后的 ``(相对路径, mtime_ns)`` 元组；目录不存在时为空元组。
    """
    if not root.is_dir():
        return ()
    entries: list[tuple[str, int]] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir():
            continue
        for file_path in child.rglob("*"):
            if not file_path.is_file():
                continue
            if "__pycache__" in file_path.parts or file_path.suffix in (".pyc", ".pyo"):
                continue
            try:
                mtime: int = file_path.stat().st_mtime_ns
            except OSError:
                mtime = 0
            entries.append((file_path.relative_to(root).as_posix(), mtime))
    return tuple(entries)


def scan_installed_extensions(
    *, force: bool = False
) -> tuple[list[ExtensionInfo], list[str]]:
    """扫描 ``extension/`` 下所有可用扩展。

    Args:
        force: 忽略缓存并重新加载插件。

    Returns:
        ``(扩展列表, 错误信息列表)``。
    """
    global _SCAN_CACHE
    root: Path = extension_root()
    if not root.is_dir():
        with _SCAN_LOCK:
            _SCAN_CACHE = None
        return [], []
    signature: tuple[tuple[str, int], ...] = _extension_signature(root)
    with _SCAN_LOCK:
        cached: tuple[
            tuple[ExtensionInfo, ...],
            tuple[str, ...],
            tuple[tuple[str, int], ...],
        ] | None = _SCAN_CACHE
        if not force and cached is not None and cached[2] == signature:
            return list(cached[0]), list(cached[1])
        infos: list[ExtensionInfo] = []
        errors: list[str] = []
        seen: set[str] = set()
        for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_dir():
                continue
            try:
                info: ExtensionInfo = load_extension_dir(child)
            except ExtensionError as exc:
                errors.append("%s：%s" % (child.name, exc))
                _LOGGER.warning("扩展加载失败 %s: %s", child.name, exc)
                continue
            if info.tab_name in seen:
                errors.append("%s：标签名与已加载扩展重复" % child.name)
                continue
            seen.add(info.tab_name)
            infos.append(info)
        _SCAN_CACHE = (tuple(infos), tuple(errors), signature)
        return list(infos), list(errors)


def get_extensions_payload() -> dict[str, Any]:
    """返回设置页使用的扩展列表数据。

    Returns:
        含 ``extensions``、``errors``、``git_available`` 与模板路径的字典。
    """
    infos, errors = scan_installed_extensions()
    enabled_names: list[str] = _config_enabled_names()
    template: Path | None = bundled_template_zip()
    return {
        "extensions": [
            info.payload(info.tab_name in enabled_names) for info in infos
        ],
        "errors": errors,
        "git_available": bool(shutil.which("git")),
        "template_zip": str(template) if template is not None else "",
        "extension_root": str(extension_root()),
    }


def _validate_zip_member(member: zipfile.ZipInfo) -> None:
    """校验 zip 成员路径，阻止路径穿越。

    Args:
        member: zip 成员。

    Raises:
        ExtensionError: 成员包含绝对路径或 ``..`` 时抛出。
    """
    name: str = member.filename.replace("\\", "/")
    parts: list[str] = [part for part in name.split("/") if part not in ("", ".")]
    if name.startswith("/") or ".." in parts or ":" in parts[0]:
        raise ExtensionError("压缩包包含非法路径：%s" % member.filename)


def _extract_zip(zip_path: Path, target: Path) -> None:
    """安全解压 zip 到目标目录。

    Args:
        zip_path: zip 文件。
        target: 目标目录。

    Raises:
        ExtensionError: 压缩包损坏或包含非法路径时抛出。
    """
    target.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.infolist():
                _validate_zip_member(member)
            archive.extractall(target)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ExtensionError("解压失败：%s" % exc) from exc


def _install_from_directory(source_dir: Path, *, record: bool = True) -> ExtensionInfo:
    """把已解压的扩展目录复制到 ``extension/`` 并登记。

    Args:
        source_dir: 扩展源目录。
        record: 是否把扩展标签名写入 ``third-party``。

    Returns:
        扩展信息。

    Raises:
        ExtensionError: 目录非法或复制失败时抛出。
    """
    metadata: dict[str, Any] = read_project_metadata(source_dir)
    base: Path = metadata["base"]
    author: str = _safe_component(str(metadata["author"]), "Unknown")
    name: str = _safe_component(str(metadata["name"]), "Extension")
    version: str = str(metadata["version"])
    folder: str = "%s-%s-%s" % (
        author,
        name,
        _safe_component("v" + format_plugin_version(version), "v0.0p0-b0"),
    )
    target: Path = extension_root() / folder
    extension_root().mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    try:
        shutil.copytree(base, target)
        info: ExtensionInfo = load_extension_dir(target)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        invalidate_extension_cache()
        raise
    invalidate_extension_cache()
    if record:
        names: list[str] = _config_enabled_names()
        if info.tab_name not in names:
            names.append(info.tab_name)
            _save_enabled_names(names)
    return info


def install_extension_zip(zip_path: str | Path) -> ExtensionInfo:
    """导入一个扩展 zip。

    Args:
        zip_path: zip 文件路径。

    Returns:
        导入后的扩展信息。

    Raises:
        ExtensionError: 文件不存在、缺少 meta.json 或校验失败时抛出。
    """
    path: Path = Path(zip_path).expanduser()
    if not path.is_file():
        raise ExtensionError("找不到扩展压缩包：%s" % path)
    with tempfile.TemporaryDirectory(prefix="hwklr-ext-") as temp_dir:
        temp_root: Path = Path(temp_dir)
        _extract_zip(path, temp_root)
        base: Path = _project_base(temp_root)
        if not (base / "meta.json").is_file():
            raise ExtensionError("扩展包缺少 meta.json")
        meta: dict[str, Any] = _read_json(base / "meta.json")
        author: str = str(meta.get("author") or "").strip()
        name: str = str(
            meta.get("name") or meta.get("extension_name") or ""
        ).strip()
        version: str = str(meta.get("version") or "").strip()
        if not author or not name or not version:
            raise ExtensionError("meta.json 必须包含 author、name、version")
        return _install_from_directory(base, record=True)


def _run_git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """执行 git 命令。

    Args:
        args: 命令参数。
        cwd: 工作目录。

    Returns:
        执行结果。

    Raises:
        ExtensionError: git 不可用或执行失败时抛出。
    """
    if not shutil.which("git"):
        raise ExtensionError("未检测到 git，无法从 Git 仓库加载扩展")
    try:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if sys.platform == "win32"
                else 0
            ),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ExtensionError("git 执行失败：%s" % exc) from exc
    if result.returncode != 0:
        detail: str = (result.stderr or result.stdout or "").strip()
        raise ExtensionError("git 执行失败：%s" % (detail[-500:] or "未知错误"))
    return result


def install_extension_git(url: str) -> ExtensionInfo:
    """从 Git 仓库克隆并导入扩展。

    Args:
        url: Git 仓库地址。

    Returns:
        导入后的扩展信息。

    Raises:
        ExtensionError: 地址为空、git 不可用或仓库结构不合法时抛出。
    """
    repository: str = str(url or "").strip()
    if not repository:
        raise ExtensionError("请输入 Git 仓库地址")
    with tempfile.TemporaryDirectory(prefix="hwklr-git-") as temp_dir:
        temp_root: Path = Path(temp_dir)
        _run_git(["clone", "--depth", "1", repository, str(temp_root / "repo")])
        repo: Path = temp_root / "repo"
        base: Path = _project_base(repo)
        if not (base / "feature" / "__init__.py").is_file():
            raise ExtensionError("仓库根目录缺少 feature/__init__.py")
        return _install_from_directory(base, record=True)


def _replace_placeholders(directory: Path, values: dict[str, str]) -> None:
    """替换模板文件中的占位符。

    Args:
        directory: 模板目录。
        values: 占位符到值的映射。
    """
    for file_path in directory.rglob("*"):
        if not file_path.is_file() or file_path.suffix.lower() in {
            ".zip",
            ".png",
            ".jpg",
            ".jpeg",
            ".ico",
            ".gif",
        }:
            continue
        try:
            text: str = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        updated: str = text
        for key, value in values.items():
            updated = updated.replace(key, value)
        if updated != text:
            file_path.write_text(updated, encoding="utf-8")


def create_plugin_project(
    name: str,
    package: str,
    *,
    template_zip: str | Path | None = None,
) -> Path:
    """使用模板在 ``HwklrVenv/extension/<包名>`` 创建插件工程。

    Args:
        name: 插件显示名。
        package: 插件包名（同时作为目录名）。
        template_zip: 自定义模板 zip；``None`` 时使用随程序分发的模板。

    Returns:
        新建工程目录。

    Raises:
        ExtensionError: 参数非法、开发环境未搭建或模板缺失时抛出。
    """
    display_name: str = str(name or "").strip()
    package_name: str = str(package or "").strip()
    if not display_name:
        raise ExtensionError("插件名不能为空")
    if not _PACKAGE_NAME.match(package_name):
        raise ExtensionError("包名只能包含字母、数字与下划线，且不能以数字开头")
    if not (venv_root() / "Scripts" / "python.exe").is_file():
        raise ExtensionError("请先在构建页搭建开发环境")
    target: Path = project_extension_root() / package_name
    if target.exists():
        raise ExtensionError("包名已存在：%s" % target)
    template: Path | None = (
        Path(template_zip).expanduser() if template_zip else bundled_template_zip()
    )
    if template is None or not template.is_file():
        raise ExtensionError("找不到插件工程模板，请检查构建设置或程序文件")
    with tempfile.TemporaryDirectory(prefix="hwklr-template-") as temp_dir:
        temp_root: Path = Path(temp_dir)
        _extract_zip(template, temp_root)
        base: Path = _project_base(temp_root)
        _replace_placeholders(
            base,
            {
                "__FEATURE_NAME__": display_name,
                "__PACKAGE_NAME__": package_name,
            },
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(base, target)
    metadata: dict[str, Any] = read_project_metadata(target)
    meta: dict[str, Any] = dict(metadata.get("meta") or {})
    meta.update({
        "author": str(metadata["author"]),
        "name": display_name,
        "package": package_name,
        "version": str(metadata["version"]),
        "update_date": str(metadata["update_date"] or time.strftime("%Y-%m-%d")),
        "official": False,
        "description": str(metadata["description"]),
    })
    (target / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target


def build_plugin_package(
    project_dir: str | Path,
    *,
    output_dir: str = "",
    log: Any = None,
    set_phase: Any = None,
) -> dict[str, Any]:
    """把一个插件工程打包为可导入的发布 zip。

    Args:
        project_dir: 插件工程根目录。
        output_dir: 输出目录；空字符串使用项目默认 build 目录。
        log: 单行日志回调。
        set_phase: ``(phase, message, progress)`` 回调。

    Returns:
        含 ``kind``、``path``、``size``、``name``、``version`` 的结果字典。

    Raises:
        ExtensionError: 工程不合法或写文件失败时抛出。
    """
    def emit(message: str) -> None:
        if callable(log):
            log(message)

    def phase(name: str, message: str, progress: int) -> None:
        if callable(set_phase):
            set_phase(name, message, progress)

    base: Path = _project_base(Path(project_dir))
    info: ExtensionInfo = load_extension_dir(base)
    version: str = str(info.version)
    update_date: str = info.update_date or time.strftime("%Y-%m-%d")
    # 保留 4.4.1 新增的 schema/id/config/db/packaging 等未知键。
    meta: dict[str, Any] = dict(info.spec.raw)
    meta.update({
        "author": info.author,
        "name": info.tab_name,
        "package": info.package,
        "version": version,
        "update_date": update_date,
        "official": info.official,
        "description": info.description,
    })
    (base / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    emit("已生成 meta.json：%s" % (base / "meta.json"))

    # 延迟导入，避免扩展模块与构建模块在导入期互相依赖。
    from hwklr.features.build.packager import resolve_output_dir

    output_root: Path = resolve_output_dir(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    file_name: str = "%s-%s-%s.zip" % (
        _safe_component(info.author, "Unknown"),
        _safe_component(info.tab_name, "Extension"),
        _safe_component("v" + format_plugin_version(version), "v0.0p0-b0"),
    )
    archive_path: Path = output_root / file_name
    if archive_path.exists():
        archive_path.unlink()

    phase("package", "正在压缩插件发布包", 30)
    files: list[Path] = [
        item
        for item in base.rglob("*")
        if item.is_file()
        and "__pycache__" not in item.parts
        and item.suffix.lower() not in {".pyc", ".pyo"}
        and ".git" not in item.parts
        and item != archive_path
    ]
    total: int = max(len(files), 1)
    try:
        with zipfile.ZipFile(
            archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            for index, file_path in enumerate(files, start=1):
                archive.write(file_path, arcname=file_path.relative_to(base).as_posix())
                if index % 50 == 0 or index == total:
                    progress: int = 30 + int(index * 60 / total)
                    phase("package", "压缩插件 %d/%d" % (index, total), min(progress, 95))
    except OSError as exc:
        raise ExtensionError("写入发布包失败：%s" % exc) from exc
    size: int = archive_path.stat().st_size
    emit("插件发布包：%s（%.1f KB）" % (archive_path, size / 1024))
    phase("done", "插件发布包构建完成", 100)
    return {
        "kind": "plugin",
        "path": str(archive_path),
        "size": size,
        "name": info.tab_name,
        "version": info.version_display,
    }
