# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-10 10:00
# 文件名: contracts.py
# 主要用途: 跨功能共享的类型化契约：任务状态/类型、Job 阶段、错误码与 Action 参数规格。
# 文件版本: 4.4.0
"""跨功能共享的类型化契约。

本模块只依赖标准库，不能导入 :mod:`hwklr.features` 或 :mod:`hwklr.config`，
避免 config → features → settings → config 的导入环。UI/功能层可以依赖本模块。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, TypedDict

__version__ = "4.4.0"
__author__ = "Gary"
__all__ = [
    "ActionRegistry",
    "ActionSpec",
    "ActionValidationError",
    "ApiResult",
    "ErrorCode",
    "JobKind",
    "JobPhase",
    "LoginPhase",
    "ParamSpec",
    "QUIZ_KINDS",
    "SUCCESS_STATUSES",
    "TERMINAL_STATUSES",
    "TaskKind",
    "TaskStatus",
    "ValidationMode",
    "coerce_bool",
    "coerce_int",
    "coerce_str",
]


class TaskStatus(str, enum.Enum):
    """任务在一次完成 job 中的运行状态（wire 值保持中文）。"""

    QUEUED = "等待队列"
    RUNNING = "进行中"
    COMPLETED = "完成"
    PUBLISHED = "已发布"
    FILLED = "已填写"
    FAILED = "失败"
    CANCELLED = "已取消"
    SKIPPED = "已跳过"


SUCCESS_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.PUBLISHED, TaskStatus.FILLED}
)
TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.PUBLISHED,
        TaskStatus.FILLED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.SKIPPED,
    }
)


class TaskKind(str, enum.Enum):
    """课程任务类型（wire 值保持中文）。"""

    VIDEO = "视频"
    DOCUMENT = "文档"
    QUIZ = "测验"
    LESSON_QUIZ = "随堂测验"
    HOMEWORK = "作业"
    EXAM = "考试"
    DISCUSSION = "讨论"
    RICH_TEXT = "富文本"
    LIVE = "直播"


QUIZ_KINDS: frozenset[str] = frozenset(
    {
        TaskKind.QUIZ.value,
        TaskKind.LESSON_QUIZ.value,
        TaskKind.HOMEWORK.value,
        TaskKind.EXAM.value,
    }
)


class JobPhase(str, enum.Enum):
    """完成/登录/同步 job 的 phase 字符串。"""

    IDLE = "idle"
    STARTING = "starting"
    LOGIN = "login"
    DB = "db"
    VIDEO = "video"
    DOCUMENT = "document"
    QUIZ = "quiz"
    DISCUSSION = "discussion"
    SERIAL = "serial"
    VERIFYING = "verifying"
    DONE = "done"
    CANCELLED = "cancelled"
    ERROR = "error"


class LoginPhase(str, enum.Enum):
    """登录 job 的专用阶段。"""

    IDLE = "idle"
    STARTING = "starting"
    AUTO = "auto"
    BROWSER = "browser"
    NEED_VISIBLE = "need_visible"
    DONE = "done"
    ERROR = "error"


class JobKind(str, enum.Enum):
    """后台 job 种类。"""

    COMPLETION = "completion"
    LOGIN = "login"
    ANSWER_SYNC = "answer_sync"
    SOLUTION = "solution"
    BUILD = "build"
    PLUGIN_BUILD = "plugin_build"


class ErrorCode(str, enum.Enum):
    """稳定的错误码；UI 不应再依赖中文错误文本做分支。"""

    OK = "ok"
    UNKNOWN = "unknown"
    INVALID_PARAMS = "invalid_params"
    AUTH_REQUIRED = "auth_required"
    BANK_MISSING = "bank_missing"
    NO_TEST_ID = "no_test_id"
    SPOC_UNSUPPORTED = "spoc_unsupported"
    PAGE_BLOCKED = "page_blocked"
    TIMEOUT = "timeout"
    SUBMISSION_UNCONFIRMED = "submission_unconfirmed"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"
    DB_ERROR = "db_error"
    INTERNAL = "internal"


class ApiResult(TypedDict, total=False):
    """桥接返回值；``ok`` 必有，``data/error/code`` 按情况出现。"""

    ok: bool
    data: Any
    error: str
    code: str


class ValidationMode(str, enum.Enum):
    """Action 参数校验模式。"""

    OFF = "off"
    COERCE = "coerce"
    STRICT = "strict"


class ActionValidationError(ValueError):
    """Action 参数不符合声明时抛出。"""


def coerce_bool(value: Any) -> bool:
    """把常见表示转换为 bool。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "是"}
    return bool(value)


def coerce_int(value: Any) -> int:
    """把值转换为 int；bool 不作为 int 接受。"""
    if isinstance(value, bool):
        raise ActionValidationError("参数不能是布尔值")
    return int(value)


def coerce_str(value: Any) -> str:
    """把值转换为 str。"""
    return str(value)


@dataclass(frozen=True)
class ParamSpec:
    """一个 action 参数的声明。"""

    name: str
    type: type | tuple[type, ...] = object
    required: bool = False
    default: Any = None
    choices: tuple[Any, ...] = ()
    coerce: Callable[[Any], Any] | None = None
    description: str = ""


@dataclass(frozen=True)
class ActionSpec:
    """一个 action 的元数据与参数声明。"""

    name: str
    params: tuple[ParamSpec, ...] = ()
    description: str = ""
    risk: str = "read"
    aliases: tuple[str, ...] = ()
    validation: ValidationMode = ValidationMode.COERCE


class ActionRegistry:
    """ActionSpec 的查找与参数校验。"""

    def __init__(self, specs: Iterable[ActionSpec]) -> None:
        self._by_name: dict[str, ActionSpec] = {}
        for spec in specs:
            self._by_name[spec.name] = spec
            for alias in spec.aliases:
                self._by_name[alias] = spec

    def get(self, name: str) -> ActionSpec | None:
        """按动作名/别名返回 spec。"""
        return self._by_name.get(str(name or ""))

    def validate(
        self, spec: ActionSpec, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        """按 COERCE/STRICT 模式校验并返回新参数字典。

        COERCE 会补默认值、转换声明类型；未知额外参数保留。
        """
        source: dict[str, Any] = dict(params or {})
        if spec.validation is ValidationMode.OFF:
            return source
        result: dict[str, Any] = dict(source)
        for param in spec.params:
            present: bool = param.name in source
            value: Any = source.get(param.name)
            if not present or value is None:
                if param.default is not None:
                    result[param.name] = param.default
                    continue
                if param.required:
                    raise ActionValidationError("缺少参数: %s" % param.name)
                continue
            if param.type is not object and not isinstance(value, param.type):
                if param.coerce is not None:
                    try:
                        value = param.coerce(value)
                    except (TypeError, ValueError) as exc:
                        raise ActionValidationError(
                            "参数 %s 格式不正确" % param.name
                        ) from exc
                else:
                    raise ActionValidationError(
                        "参数 %s 类型不正确" % param.name
                    )
            elif param.coerce is not None:
                try:
                    value = param.coerce(value)
                except (TypeError, ValueError) as exc:
                    raise ActionValidationError(
                        "参数 %s 格式不正确" % param.name
                    ) from exc
            if param.choices and value not in param.choices:
                raise ActionValidationError(
                    "参数 %s 必须是 %s 之一" % (param.name, ", ".join(map(str, param.choices)))
                )
            result[param.name] = value
        if spec.validation is ValidationMode.STRICT:
            allowed = {param.name for param in spec.params}
            unknown = set(result) - allowed
            if unknown:
                raise ActionValidationError(
                    "未知参数: %s" % ", ".join(sorted(unknown))
                )
        return result
