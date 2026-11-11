# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-11 10:00
# 文件名: settings.py
# 主要用途: 设置分组框架（FeatureSettingsGroup）、“设置”标签页功能实现、第三方扩展加载/启用管理与数据库信息展示。
# 文件版本: 4.4.3
"""设置分组与设置页功能。

V2 起，每个功能通过 :class:`FeatureSettingsGroup` 注册自己的设置板块：
- 字段定义（文本、密码、数字、下拉、开关）；
- ``export`` 控制写入 ``config.json`` 的字段；
- ``is_complete`` / ``missing_labels`` 用于标签页的必要设置校验。

设置页本身包含“通用”板块；其他标签的设置组由 ``WindowView`` 注册进来。
"""
from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from hwklr import __version__ as APP_VERSION
from hwklr import db
from hwklr.config import load_config, update_config
from hwklr.contracts import ActionSpec
from hwklr.features.base import ApiResult, Feature, failure, success

__version__ = "4.4.3"
__author__ = "Gary"
__all__ = ["FeatureSettingsGroup", "SettingsFeature", "SettingsFieldSpec"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


@dataclass(frozen=True)
class SettingsFieldSpec:
    """一个设置字段的静态定义。

    ``is_necessary`` 只用于提示字段是否影响正常使用，不会阻止离开设置页；
    设为 ``False`` 时前端以灰字与灰色星号标记“可选填”。

    ``alert`` 标记高级/高风险设置；前端在该字段被修改并保存（含自动保存）时
    弹出二次确认，避免用户误改导致功能失效。

    ``tooltip`` 非空时，设置页在名称末尾显示 ``(i)``，悬浮时展示
    “名称：tooltip”气泡；``help`` 仍是字段下方的常驻说明。
    """

    key: str
    label: str
    kind: str = "text"
    placeholder: str = ""
    help: str = ""
    # 设置项名称旁的 (i) 悬浮气泡内容；为空时不显示帮助按钮。
    tooltip: str = ""
    options: tuple[tuple[str, str], ...] = ()
    secret: bool = False
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    strip: bool = True
    is_necessary: bool = True
    alert: bool = False


class FeatureSettingsGroup:
    """功能设置板块。

    每个标签页通过只读的 ``settings_group`` 属性提供一个实例；设置页负责
    渲染字段、收集值并调用 :meth:`export` 生成配置补丁。
    """

    def __init__(
        self,
        group_id: str,
        title: str,
        description: str,
        field_specs: tuple[SettingsFieldSpec, ...],
        values_getter: Callable[[], dict[str, Any]],
        exporter: Callable[[dict[str, Any]], dict[str, Any]],
        complete_checker: Callable[[], bool],
        missing_getter: Callable[[], list[str]],
        enabled_getter: Callable[[], bool] | None = None,
        enabled_setter: Callable[[bool], None] | None = None,
        enabled_editable: bool = False,
    ) -> None:
        """初始化设置板块。

        Args:
            group_id: 板块唯一标识，也是配置分组名（通用板块除外）。
            title: 设置页显示的板块标题。
            description: 板块说明。
            field_specs: 字段定义。
            values_getter: 从 config.json 读取当前值的回调。
            exporter: 把规范化后的值转换为配置补丁的回调。
            complete_checker: 判断该功能必要设置是否完成的回调。
            missing_getter: 返回缺失设置名称列表的回调。
            enabled_getter: 读取功能是否启用的回调；``None`` 表示不显示开关。
            enabled_setter: 设置功能启用状态的回调。
            enabled_editable: 是否允许在板块右上角切换启用状态。
        """
        self.group_id: str = group_id
        self.title: str = title
        self.description: str = description
        self._field_specs: tuple[SettingsFieldSpec, ...] = field_specs
        self._values_getter: Callable[[], dict[str, Any]] = values_getter
        self._exporter: Callable[[dict[str, Any]], dict[str, Any]] = exporter
        self._complete_checker: Callable[[], bool] = complete_checker
        self._missing_getter: Callable[[], list[str]] = missing_getter
        self._enabled_getter: Callable[[], bool] | None = enabled_getter
        self._enabled_setter: Callable[[bool], None] | None = enabled_setter
        self._enabled_editable: bool = bool(enabled_editable)

    def bind_enabled(
        self,
        getter: Callable[[], bool],
        setter: Callable[[bool], None],
        editable: bool = True,
    ) -> None:
        """为板块绑定功能启用开关。

        Args:
            getter: 读取启用状态。
            setter: 设置启用状态。
            editable: 是否允许用户切换。
        """
        self._enabled_getter = getter
        self._enabled_setter = setter
        self._enabled_editable = bool(editable)

    @property
    def enabled_editable(self) -> bool:
        """返回板块是否显示启用开关。

        Returns:
            显示返回 ``True``。
        """
        return self._enabled_editable and self._enabled_getter is not None

    def is_enabled(self) -> bool:
        """读取板块对应功能的启用状态。

        Returns:
            启用返回 ``True``；未绑定开关时返回 ``True``。
        """
        if self._enabled_getter is None:
            return True
        try:
            return bool(self._enabled_getter())
        except Exception:  # 配置损坏时不影响设置页渲染。
            return True

    def set_enabled(self, enabled: bool) -> None:
        """设置板块对应功能的启用状态。

        Args:
            enabled: 是否启用。
        """
        if self._enabled_setter is not None:
            self._enabled_setter(bool(enabled))

    @property
    def field_specs(self) -> tuple[SettingsFieldSpec, ...]:
        """返回字段定义元组。

        Returns:
            字段定义。
        """
        return self._field_specs

    def values(self) -> dict[str, Any]:
        """读取当前配置值。

        Returns:
            字段键到值的映射。
        """
        values: dict[str, Any] = self._values_getter()
        return {spec.key: values.get(spec.key, "") for spec in self._field_specs}

    def fields(self) -> list[dict[str, Any]]:
        """返回供前端渲染的字段数据。

        Returns:
            字段数据列表。
        """
        values: dict[str, Any] = self.values()
        result: list[dict[str, Any]] = []
        for spec in self._field_specs:
            entry: dict[str, Any] = {
                "key": spec.key,
                "label": spec.label,
                "kind": spec.kind,
                "value": values.get(spec.key, ""),
                "placeholder": spec.placeholder,
                "help": spec.help,
                "tooltip": spec.tooltip,
                "options": [
                    {"value": value, "label": label} for value, label in spec.options
                ],
                "secret": spec.secret,
                "min": spec.min_value,
                "max": spec.max_value,
                "step": spec.step,
                "is_necessary": spec.is_necessary,
                "alert": spec.alert,
            }
            # #features 类型额外输出每行的名称、版本与开发标记，供前端渲染表格。
            if spec.kind == "features":
                raw_dev: Any = values.get(spec.key)
                dev_map: dict[str, Any] = raw_dev if isinstance(raw_dev, dict) else {}
                entry["rows"] = [
                    {
                        "name": name,
                        "version": version,
                        "dev": _as_dev_state(dev_map.get(name)),
                    }
                    for name, version in spec.options
                ]
            result.append(entry)
        return result

    def normalize(self, raw_values: dict[str, Any]) -> dict[str, Any]:
        """按字段类型校验并规范化用户提交的值。

        Args:
            raw_values: 前端提交的原始值。

        Returns:
            规范化后的值。

        Raises:
            ValueError: 数字或下拉值非法时抛出。
        """
        current: dict[str, Any] = self.values()
        normalized: dict[str, Any] = dict(current)
        for spec in self._field_specs:
            if spec.key not in raw_values:
                continue
            # #扩展加载器是纯交互控件，不参与配置值收集。
            if spec.kind == "extensions":
                continue
            raw: Any = raw_values.get(spec.key)
            if spec.kind == "switch":
                normalized[spec.key] = _as_bool(raw)
            elif spec.kind == "number":
                try:
                    number: float = float(raw)
                except (TypeError, ValueError) as exc:
                    raise ValueError("%s 必须是数字" % spec.label) from exc
                if spec.min_value is not None and number < spec.min_value:
                    raise ValueError("%s 不能小于 %s" % (spec.label, spec.min_value))
                if spec.max_value is not None and number > spec.max_value:
                    raise ValueError("%s 不能大于 %s" % (spec.label, spec.max_value))
                normalized[spec.key] = number
            elif spec.kind == "select":
                text: str = str(raw or "")
                allowed: set[str] = {value for value, _label in spec.options}
                if allowed and text not in allowed:
                    raise ValueError("%s 的取值不合法" % spec.label)
                normalized[spec.key] = text
            elif spec.kind == "features":
                current_map: Any = normalized.get(spec.key)
                merged: dict[str, str] = {}
                if isinstance(current_map, dict):
                    for name, state in current_map.items():
                        merged[str(name)] = (
                            "dev" if _as_dev_state(state) else "release"
                        )
                if isinstance(raw, dict):
                    allowed_names: set[str] = {
                        name for name, _version in spec.options
                    }
                    for name, state in raw.items():
                        if str(name) not in allowed_names:
                            continue
                        merged[str(name)] = (
                            "dev" if _as_dev_state(state) else "release"
                        )
                # 只保留当前登记的功能，避免配置中残留已移除功能。
                normalized[spec.key] = {
                    name: merged.get(name, "release")
                    for name, _version in spec.options
                }
            else:
                text = str(raw if raw is not None else "")
                normalized[spec.key] = text.strip() if spec.strip else text
        return normalized

    def export(self, values: dict[str, Any] | None = None) -> dict[str, Any]:
        """生成写入 config.json 的补丁。

        Args:
            values: 已规范化的值；``None`` 时使用当前配置值。

        Returns:
            配置补丁字典。
        """
        return self._exporter(values if values is not None else self.values())

    def is_complete(self) -> bool:
        """判断该功能必要设置是否完整。

        Returns:
            完整返回 ``True``。
        """
        return bool(self._complete_checker())

    def missing_labels(self) -> list[str]:
        """返回缺失设置的可读名称。

        Returns:
            缺失项列表。
        """
        return list(self._missing_getter())

    def payload(self) -> dict[str, Any]:
        """返回设置页需要的板块数据。

        Returns:
            含标题、字段、完整性与缺失项的数据。
        """
        return {
            "group_id": self.group_id,
            "title": self.title,
            "description": self.description,
            "fields": self.fields(),
            "complete": self.is_complete(),
            "missing": self.missing_labels(),
            "enabled": self.is_enabled(),
            "enabled_editable": self.enabled_editable,
        }


def _as_dev_state(value: Any) -> bool:
    """判断 features 字段中的一项是否标记为开发构建。

    Args:
        value: ``True`` / ``False``，或 ``"dev"`` / ``"release"`` 等前端值。

    Returns:
        标记为 dev 返回 ``True``。
    """
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "dev", "是"}


def _as_bool(value: Any) -> bool:
    """把前端值转换为布尔值。

    Args:
        value: 任意前端值。

    Returns:
        布尔结果。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "on", "是"}


def _merge_patch(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """递归合并两个配置补丁。

    Args:
        base: 已合并的补丁。
        patch: 新补丁。

    Returns:
        合并后的新字典。
    """
    merged: dict[str, Any] = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_patch(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


class SettingsFeature(Feature):
    """“设置”标签页功能。

    通用设置（用户名）由本类自己持有；其他标签通过
    :meth:`register_group` 注册各自的设置板块。
    """

    @classmethod
    def action_specs(cls) -> tuple[ActionSpec, ...]:
        """返回设置页动作声明。"""
        return (
            ActionSpec("get_settings"),
            ActionSpec("save_settings"),
            ActionSpec("get_bank_info"),
            ActionSpec("get_extensions"),
            ActionSpec("pick_extension_zip"),
            ActionSpec("load_extension_zip"),
            ActionSpec("load_extension_git"),
            ActionSpec("set_extension_enabled"),
            ActionSpec("set_group_enabled"),
            ActionSpec("pick_plugin_template"),
        )

    def __init__(self, universal_param: dict[str, Any]) -> None:
        """初始化设置功能。

        Args:
            universal_param: 窗口层注入的通用参数。
        """
        super().__init__(universal_param)
        self._groups: list[FeatureSettingsGroup] = [self._build_general_group()]

    def _build_general_group(self) -> FeatureSettingsGroup:
        """构建通用设置板块。

        Returns:
            含用户名设置的板块。
        """

        def values_getter() -> dict[str, Any]:
            """读取通用设置。"""
            config: dict[str, Any] = load_config()
            return {
                "update_notice": bool(config.get("update_notice", True)),
                "username": str(config.get("username") or ""),
            }

        def exporter(values: dict[str, Any]) -> dict[str, Any]:
            """导出通用设置。"""
            return {
                "update_notice": bool(values.get("update_notice", True)),
                "username": str(values.get("username") or ""),
            }

        return FeatureSettingsGroup(
            group_id="general",
            title="通用",
            description="所有功能共用的账号信息与更新提示。",
            field_specs=(
                SettingsFieldSpec(
                    key="update_notice",
                    label="更新提示",
                    kind="switch",
                    tooltip=(
                        "启动时检查 GitHub 与 GitCode 的新版本；"
                        "关闭后不再检查或提示更新。"
                    ),
                ),
                SettingsFieldSpec(
                    key="username",
                    label="学号 / 账号",
                    kind="text",
                    placeholder="请输入学号或账号",
                    help="高铁纵横与 C 程序设计共用该用户名。",
                    tooltip=(
                        "高铁纵横与 C 程序设计共用的学号或账号，"
                        "保存在本机 config.json。"
                    ),
                ),
                SettingsFieldSpec(
                    key="extensions",
                    label="加载扩展",
                    kind="extensions",
                    is_necessary=False,
                    help=(
                        "从本地 zip 或 Git 仓库导入第三方功能扩展。导入成功后会显示"
                        "在下方列表中，可随时启用或停用。"
                    ),
                    tooltip=(
                        "从本地 zip 或 Git 仓库导入第三方扩展；"
                        "导入后在列表中启用或停用。"
                    ),
                ),
            ),
            values_getter=values_getter,
            exporter=exporter,
            complete_checker=lambda: True,
            missing_getter=lambda: [],
        )

    @property
    def settings_group(self) -> FeatureSettingsGroup:
        """返回设置页自身的通用设置组。

        Returns:
            通用设置组。
        """
        return self._groups[0]

    @property
    def about_meta(self) -> Any:
        """返回设置功能自身的元信息（不展示在关于页列表中）。

        Returns:
            设置功能元信息组。
        """
        from hwklr.features.about import AboutMetadataGroup

        return AboutMetadataGroup(
            name="设置",
            package="SETTINGS",
            author="Gary",
            version=APP_VERSION,
            update_date="2026-11-03",
            official=True,
            feature_key="设置",
            is_software=False,
        )

    def register_group(self, group: FeatureSettingsGroup) -> None:
        """注册一个功能的设置板块。

        Args:
            group: 功能设置组。
        """
        if any(item.group_id == group.group_id for item in self._groups):
            return
        self._groups.append(group)

    def unregister_group(self, group_id: str) -> None:
        """移除一个设置板块（用于测试插件热替换）。

        Args:
            group_id: 板块 ID；通用板块不可移除。
        """
        if group_id == "general":
            return
        self._groups = [
            item for item in self._groups if item.group_id != group_id
        ]

    @property
    def groups(self) -> list[FeatureSettingsGroup]:
        """返回所有设置板块副本。

        Returns:
            设置板块列表。
        """
        return list(self._groups)

    def _payload(self) -> dict[str, Any]:
        """生成设置页数据。

        Returns:
            含所有板块、端口与版本的数据。
        """
        context: dict[str, Any] = self._universal_param.get("context", {})
        return {
            "groups": [group.payload() for group in self._groups],
            "port": int(context.get("port", 0)),
            "version": APP_VERSION,
        }

    def handle(self, action: str, params: dict[str, Any]) -> ApiResult:
        """分发设置页动作。

        Args:
            action: 动作名称。
            params: 动作参数。

        Returns:
            统一格式的结果字典。
        """
        if action == "get_settings":
            return success(self._payload())
        if action == "save_settings":
            return self._save_settings(params)
        if action == "get_bank_info":
            return self._get_bank_info(params)
        if action == "get_extensions":
            return self._get_extensions(params)
        if action == "pick_extension_zip":
            return self._pick_extension_zip(params)
        if action == "load_extension_zip":
            return self._load_extension_zip(params)
        if action == "load_extension_git":
            return self._load_extension_git(params)
        if action == "set_extension_enabled":
            return self._set_extension_enabled(params)
        if action == "set_group_enabled":
            return self._set_group_enabled(params)
        if action == "pick_plugin_template":
            return self._pick_plugin_template(params)
        return failure("未知动作: %s" % action)

    def _save_settings(self, params: dict[str, Any]) -> ApiResult:
        """保存所有设置板块提交的值。

        Args:
            params: 必须包含 ``groups`` 字典。

        Returns:
            保存后的完整设置数据。
        """
        raw_groups: Any = params.get("groups")
        if not isinstance(raw_groups, dict):
            return failure("设置数据格式错误")
        patch: dict[str, Any] = {}
        saved_any: bool = False
        for group in self._groups:
            raw_values: Any = raw_groups.get(group.group_id)
            if not isinstance(raw_values, dict):
                continue
            try:
                normalized: dict[str, Any] = group.normalize(raw_values)
                exported: dict[str, Any] = group.export(normalized)
            except ValueError as exc:
                return failure(str(exc))
            patch = _merge_patch(patch, exported)
            saved_any = True
        if not saved_any:
            return failure("没有可保存的设置")
        try:
            update_config(patch)
        except OSError as exc:
            return failure("保存设置失败: %s" % exc)
        return success(self._payload())

    # ---------------------------------------------------------------- 扩展
    def _dialogs(self) -> dict[str, Any]:
        """返回窗口层注入的对话框回调。

        Returns:
            回调字典。
        """
        value: Any = self._universal_param.get("dialogs")
        return value if isinstance(value, dict) else {}

    def _register_extension_callback(self) -> Any:
        """返回窗口层注入的扩展注册回调。

        Returns:
            可调用对象；未注入时返回 ``None``。
        """
        value: Any = self._universal_param.get("extensions")
        if not isinstance(value, dict):
            return None
        callback: Any = value.get("register_dir")
        return callback if callable(callback) else None

    def _register_loaded_extension(self, path: str) -> dict[str, Any]:
        """把刚导入的扩展注册为运行期标签。

        Args:
            path: 扩展目录。

        Returns:
            注册结果；回调不存在时返回空字典。
        """
        callback: Any = self._register_extension_callback()
        if not callable(callback):
            return {}
        result: Any = callback(path, False)
        return result if isinstance(result, dict) else {}

    def _get_extensions(self, params: dict[str, Any]) -> ApiResult:
        """返回已导入扩展列表。

        Args:
            params: 未使用的动作参数。

        Returns:
            扩展列表、错误、git 可用性与模板路径。
        """
        from hwklr.features.extensions import get_extensions_payload

        return success(get_extensions_payload())

    def _pick_extension_zip(self, params: dict[str, Any]) -> ApiResult:
        """弹出文件选择框选择扩展 zip。

        Args:
            params: 未使用的动作参数。

        Returns:
            ``{"path": str}``；用户取消时 path 为空。
        """
        picker: Any = self._dialogs().get("pick_file")
        if not callable(picker):
            return failure("当前环境不支持文件选择")
        try:
            path: Any = picker(
                "选择扩展压缩包",
                "",
                ("Zip 压缩包 (*.zip)",),
            )
        except Exception as exc:
            return failure("打开文件选择框失败：%s" % exc)
        return success({"path": str(path or "")})

    def _load_extension_zip(self, params: dict[str, Any]) -> ApiResult:
        """导入本地扩展 zip 并立即加载。

        Args:
            params: 必须包含 ``path``。

        Returns:
            导入后的扩展信息与标签名。
        """
        from hwklr.features.extensions import ExtensionError, install_extension_zip

        path: str = str(params.get("path") or "").strip()
        if not path:
            return failure("未选择扩展压缩包")
        try:
            info = install_extension_zip(path)
        except ExtensionError as exc:
            return failure(str(exc))
        try:
            register_result: dict[str, Any] = self._register_loaded_extension(
                str(info.path)
            )
        except Exception as exc:
            return failure("扩展已解压，但运行期加载失败：%s" % exc)
        return success({
            "extension": info.payload(True),
            "tab": register_result.get("tab", info.tab_name),
        })

    def _load_extension_git(self, params: dict[str, Any]) -> ApiResult:
        """从 Git 仓库导入扩展并立即加载。

        Args:
            params: 必须包含 ``url``。

        Returns:
            导入后的扩展信息与标签名。
        """
        from hwklr.features.extensions import ExtensionError, install_extension_git

        url: str = str(params.get("url") or "").strip()
        if not url:
            return failure("请输入 Git 仓库地址")
        try:
            info = install_extension_git(url)
        except ExtensionError as exc:
            return failure(str(exc))
        try:
            register_result: dict[str, Any] = self._register_loaded_extension(
                str(info.path)
            )
        except Exception as exc:
            return failure("扩展已解压，但运行期加载失败：%s" % exc)
        return success({
            "extension": info.payload(True),
            "tab": register_result.get("tab", info.tab_name),
        })

    def _set_extension_enabled(self, params: dict[str, Any]) -> ApiResult:
        """启用或停用一个第三方扩展。

        Args:
            params: 必须包含 ``name`` 与 ``enabled``。

        Returns:
            最新的扩展列表数据。
        """
        from hwklr.features.extensions import (
            get_extensions_payload,
            set_extension_enabled,
        )

        name: str = str(params.get("name") or "").strip()
        if not name:
            return failure("缺少扩展名")
        set_extension_enabled(name, _as_bool(params.get("enabled")))
        return success(get_extensions_payload())

    def _set_group_enabled(self, params: dict[str, Any]) -> ApiResult:
        """切换某个功能设置板块右上角的启用开关。

        Args:
            params: 必须包含 ``group_id`` 与 ``enabled``。

        Returns:
            保存后的完整设置数据。
        """
        group_id: str = str(params.get("group_id") or "").strip()
        target: FeatureSettingsGroup | None = next(
            (item for item in self._groups if item.group_id == group_id), None
        )
        if target is None:
            return failure("未知设置板块: %s" % group_id)
        if not target.enabled_editable:
            return failure("该设置板块不支持启用开关")
        target.set_enabled(_as_bool(params.get("enabled")))
        return success(self._payload())

    def _pick_plugin_template(self, params: dict[str, Any]) -> ApiResult:
        """选择插件工程模板 zip。

        Args:
            params: 未使用的动作参数。

        Returns:
            ``{"path": str}``；用户取消时 path 为空。
        """
        picker: Any = self._dialogs().get("pick_file")
        if not callable(picker):
            return failure("当前环境不支持文件选择")
        try:
            path: Any = picker(
                "选择插件工程模板",
                "",
                ("Zip 压缩包 (*.zip)",),
            )
        except Exception as exc:
            return failure("打开文件选择框失败：%s" % exc)
        return success({"path": str(path or "")})

    def _get_bank_info(self, params: dict[str, Any]) -> ApiResult:
        """列出所有功能数据库及记录数量。

        Args:
            params: 未使用的动作参数。

        Returns:
            形如 ``{"banks": [...]}`` 的结果。
        """
        try:
            banks: list[dict[str, Any]] = db.get_db_manager().bank_info()
        except db.DbError as exc:
            _LOGGER.warning("读取数据库信息失败: %s", exc)
            return failure("读取数据库信息失败：%s" % exc)
        return success({"banks": banks})
