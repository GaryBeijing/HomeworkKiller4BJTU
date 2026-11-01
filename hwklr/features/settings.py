# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-01 12:40
# 文件名: settings.py
# 主要用途: 设置分组框架（FeatureSettingsGroup）与“设置”标签页功能实现，支持构建功能的 Feature 开发标记表。
# 文件版本: 2.1.0
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
from hwklr import runtime_data
from hwklr.config import load_config, update_config
from hwklr.features.base import ApiResult, Feature, failure, success

__version__ = "2.1.0"
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
    """

    key: str
    label: str
    kind: str = "text"
    placeholder: str = ""
    help: str = ""
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
        """
        self.group_id: str = group_id
        self.title: str = title
        self.description: str = description
        self._field_specs: tuple[SettingsFieldSpec, ...] = field_specs
        self._values_getter: Callable[[], dict[str, Any]] = values_getter
        self._exporter: Callable[[dict[str, Any]], dict[str, Any]] = exporter
        self._complete_checker: Callable[[], bool] = complete_checker
        self._missing_getter: Callable[[], list[str]] = missing_getter

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
            """读取用户名。"""
            config: dict[str, Any] = load_config()
            return {"username": str(config.get("username") or "")}

        def exporter(values: dict[str, Any]) -> dict[str, Any]:
            """导出用户名。"""
            return {"username": str(values.get("username") or "")}

        return FeatureSettingsGroup(
            group_id="general",
            title="通用",
            description="所有功能共用的账号信息。",
            field_specs=(
                SettingsFieldSpec(
                    key="username",
                    label="学号 / 账号",
                    kind="text",
                    placeholder="请输入学号或账号",
                    help="高铁纵横与 C 程序设计共用该用户名。",
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

    def register_group(self, group: FeatureSettingsGroup) -> None:
        """注册一个功能的设置板块。

        Args:
            group: 功能设置组。
        """
        if any(item.group_id == group.group_id for item in self._groups):
            return
        self._groups.append(group)

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

    def _get_bank_info(self, params: dict[str, Any]) -> ApiResult:
        """列出所有功能知识库及题量。

        Args:
            params: 未使用的动作参数。

        Returns:
            形如 ``{"banks": [...]}`` 的结果。
        """
        banks: list[dict[str, Any]] = []
        for feature_name, versions in runtime_data.list_banks().items():
            for version in versions:
                try:
                    data: Any = runtime_data.load_bank(feature_name, version)
                    count: int = self._count_items(data)
                except (OSError, ValueError) as exc:
                    _LOGGER.warning("读取知识库失败 %s v%s: %s", feature_name, version, exc)
                    count = 0
                banks.append({
                    "feature": feature_name,
                    "version": version,
                    "count": count,
                })
        return success({"banks": banks})

    @staticmethod
    def _count_items(data: Any) -> int:
        """统计知识库条目数量。

        Args:
            data: JSON 解析后的知识库对象。

        Returns:
            条目数量。
        """
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            items: Any = data.get("items") or data.get("questions") or []
            return len(items) if isinstance(items, list) else 0
        return 0
