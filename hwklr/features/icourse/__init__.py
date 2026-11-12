# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-12 13:00
# 文件名: __init__.py
# 主要用途: 实现“中国大学慕课”功能：登录、课程状态、任务 handler 编排、批量完成与题库同步。
# 文件版本: 4.6.1
"""中国大学慕课功能。

功能层只负责动作分发、状态缓存与 job 编排；浏览器自动化、课程解析与题库
读写分别在 ``actions``、``courses``、``hwklr.db.icoursedb`` 中实现。
所有 Playwright / requests 相关模块都在动作方法内部惰性导入，保证窗口启动
时只做轻量初始化。
"""
from __future__ import annotations

import copy
import logging
import threading
import time
from typing import Any, Final

from hwklr import db as hwklr_db
from hwklr.config import load_config
from hwklr.contracts import (
    ActionSpec,
    ParamSpec,
    JobKind,
    coerce_bool,
    coerce_int,
)
from hwklr.feature_specs import FEATURE_BY_ID
from hwklr.features.about import AboutMetadataGroup, about_meta_from_spec
from hwklr.features.base import ApiResult, Feature, failure, success
from hwklr.features.extensions import is_feature_enabled, set_feature_enabled
from hwklr.features.jobs import BackgroundJob, JobStore
from hwklr.features.settings import FeatureSettingsGroup, SettingsFieldSpec

from . import config
from .state import CourseState
from .models import (
    DONE,
    Course,
    Task,
    build_course,
    build_course_without_tasks,
    extract_term_id,
)

__version__ = "4.6.1"
__author__ = "Gary"
__all__ = ["IcourseFeature"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_FEATURE_NAME: Final[str] = "中国大学慕课"
_DB_NAME: Final[str] = "icourse"
_MAX_EVENTS: Final[int] = 200
_QUIZ_KINDS: Final[frozenset[str]] = frozenset({"测验", "随堂测验", "作业", "考试"})
_ACTION_SPECS: Final[tuple[ActionSpec, ...]] = (
    ActionSpec("get_state", description="读取登录、课程与 job 快照。"),
    ActionSpec("validate_login", description="校验当前浏览器登录态。"),
    ActionSpec("load_courses", description="刷新已选课程列表。"),
    ActionSpec(
        "select_course",
        params=(
            ParamSpec("term_id", int, required=True, coerce=coerce_int),
        ),
        description="选择课程并构建任务树。",
    ),
    ActionSpec("get_course", description="读取缓存课程树。"),
    ActionSpec(
        "start_login_job",
        params=(
            ParamSpec(
                "mode",
                str,
                default="auto",
                choices=("auto", "headless", "visible", "cookies"),
            ),
            ParamSpec("browser", str, default="auto"),
        ),
        description="启动登录后台任务。",
        risk="write",
    ),
    ActionSpec(
        "get_login_job",
        params=(ParamSpec("job_id", str, default=""),),
        description="读取登录任务快照。",
    ),
    ActionSpec(
        "cancel_login_job",
        params=(ParamSpec("job_id", str, default=""),),
        description="取消登录任务。",
        risk="write",
    ),
    ActionSpec("logout", description="退出登录并清空课程缓存。", risk="write"),
    ActionSpec(
        "start_answer_sync",
        params=(
            ParamSpec("term_id", int, default=0, coerce=coerce_int),
            ParamSpec("force", bool, default=False, coerce=coerce_bool),
        ),
        description="启动或复用题库同步任务。",
        risk="write",
    ),
    ActionSpec("get_answer_sync", description="读取题库同步快照。"),
    ActionSpec(
        "start_completion_job",
        params=(
            ParamSpec("term_id", int, required=True, coerce=coerce_int),
            ParamSpec("task_keys", list, required=True),
        ),
        description="启动批量完成任务。",
        risk="destructive",
    ),
    ActionSpec(
        "get_completion_job",
        params=(ParamSpec("job_id", str, default=""),),
        description="读取完成任务的快照。",
    ),
    ActionSpec(
        "cancel_completion_job",
        params=(ParamSpec("job_id", str, default=""),),
        description="取消当前完成任务。",
        risk="write",
    ),
)
_KIND_ORDER: Final[tuple[str, ...]] = (
    "视频",
    "文档",
    "测验",
    "随堂测验",
    "作业",
    "考试",
    "讨论",
    "富文本",
    "直播",
)

_DEFAULT_SETTINGS: Final[dict[str, Any]] = {
    "account": "",
    "password": "",
    "account_type": "icourse",
    "workers": 8,
    "video_rate": 2.0,
    "submit_quizzes": False,
    "publish_discussions": False,
    "answer_ttl_hours": 24,
    "auto_sync_answers": True,
    "download_documents": True,
    "retain_data": True,
}


def _clamp_workers(value: Any) -> int:
    """把并发数限制在 1–8。

    Args:
        value: 原始配置值。

    Returns:
        合法并发数。
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 8
    return max(1, min(8, number))


def _task_key_base(task: Task) -> str:
    """构造任务的基础 key。

    Args:
        task: 任务。

    Returns:
        形如 ``视频:123`` 的 key。
    """
    identifier = task.test_id or task.unit_id or task.content_id or 0
    return "%s:%s" % (task.kind, identifier)


class IcourseFeature(Feature):
    """“中国大学慕课”功能。"""

    @classmethod
    def action_specs(cls) -> tuple[ActionSpec, ...]:
        """返回慕课动作的参数声明。"""
        return _ACTION_SPECS

    @property
    def _member(self) -> dict[str, Any]:
        return self._state.member

    @_member.setter
    def _member(self, value: dict[str, Any]) -> None:
        self._state.member = dict(value)

    @property
    def _course_items(self) -> list[dict[str, Any]]:
        return self._state.course_items

    @_course_items.setter
    def _course_items(self, value: list[dict[str, Any]]) -> None:
        self._state.course_items = list(value)

    @property
    def _courses(self) -> list[Course]:
        return self._state.courses

    @_courses.setter
    def _courses(self, value: list[Course]) -> None:
        self._state.courses = list(value)

    @property
    def _course(self) -> Course | None:
        return self._state.selected

    @_course.setter
    def _course(self, value: Course | None) -> None:
        self._state.selected = value

    @property
    def _course_payload(self) -> dict[str, Any]:
        return self._state.payload

    @_course_payload.setter
    def _course_payload(self, value: dict[str, Any]) -> None:
        self._state.payload = dict(value)

    @property
    def _catalog_ids(self) -> set[int] | None:
        return self._state.catalog_ids

    @_catalog_ids.setter
    def _catalog_ids(self, value: set[int] | None) -> None:
        self._state.catalog_ids = value

    def __init__(self, universal_param: dict[str, Any]) -> None:
        """初始化功能状态（不做网络/浏览器操作）。

        Args:
            universal_param: 窗口层注入的通用参数。
        """
        super().__init__(universal_param)
        self._db_base_name = _DB_NAME
        self._state: CourseState = CourseState()
        self._state_lock: threading.RLock = self._state.lock
        self._answer_sync: Any | None = None
        self._answer_sync_lock: threading.RLock = threading.RLock()
        self._login_job: BackgroundJob[Any] = BackgroundJob(
            JobKind.LOGIN,
            self._idle_login(),
            include_job_id=True,
            max_events=_MAX_EVENTS,
        )
        self._job_lock: threading.RLock = threading.RLock()
        self._job: Any | None = None
        self._jobs: JobStore = JobStore()
        self._jobs.put("login", self._login_job)
        self._settings_group: FeatureSettingsGroup = self._build_settings_group()

    def shutdown(self) -> None:
        """窗口关闭时取消并等待登录、题库同步与完成任务。"""
        super().shutdown()
        self._jobs.cancel_all(timeout=0.5)

    # ------------------------------------------------------------------ 元信息
    @property
    def settings_group(self) -> FeatureSettingsGroup:
        """返回慕课设置板块。

        Returns:
            设置组。
        """
        return self._settings_group

    @property
    def about_meta(self) -> AboutMetadataGroup:
        """返回关于页元信息。

        Returns:
            慕课插件元信息。
        """
        return about_meta_from_spec(FEATURE_BY_ID["icourse"], __version__)

    def _build_settings_group(self) -> FeatureSettingsGroup:
        """构建设置字段。

        Returns:
            慕课设置组。
        """
        specs: tuple[SettingsFieldSpec, ...] = (
            SettingsFieldSpec(
                key="account",
                label="账号",
                placeholder="爱课程 / 网易邮箱 / 网易手机号",
                help="账号类型可在下方选择，不再自动识别。",
                tooltip=(
                    "爱课程、网易邮箱或网易手机号；请选择与账号匹配的类型。"
                ),
                is_necessary=False,
            ),
            SettingsFieldSpec(
                key="password",
                label="密码",
                kind="password",
                secret=True,
                strip=False,
                help="仅保存在本机 config.json，不会写入日志。",
                tooltip=(
                    "登录中国大学慕课的密码，仅保存在本机 config.json，"
                    "不会写入日志。"
                ),
                is_necessary=False,
            ),
            SettingsFieldSpec(
                key="account_type",
                label="账号类型",
                kind="select",
                options=(
                    ("icourse", "爱课程（含手机号注册）"),
                    ("mail", "网易邮箱"),
                    ("phone", "网易手机号"),
                ),
                help="爱课堂账号即使使用手机号注册，也应选择“爱课程”。",
                tooltip=(
                    "选择账号所属类型；爱课堂账号即使使用手机号注册也应选择"
                    "“爱课程”。"
                ),
                is_necessary=False,
            ),
            SettingsFieldSpec(
                key="workers",
                label="最大并行数",
                kind="number",
                min_value=1,
                max_value=8,
                step=1,
                alert=True,
                help="默认 8（上限），仅用于视频；并发过高可能触发站点限流。",
                tooltip="仅用于视频的并发播放数，默认 8；并发过高可能触发站点限流。",
                is_necessary=False,
            ),
            SettingsFieldSpec(
                key="video_rate",
                label="视频倍速",
                kind="number",
                min_value=1,
                max_value=2,
                step=0.25,
                help="1–2 倍速。",
                tooltip="视频播放倍速，范围 1–2 倍。",
                is_necessary=False,
            ),
            SettingsFieldSpec(
                key="submit_quizzes",
                label="自动提交测验",
                kind="switch",
                alert=True,
                help="关闭时只填写答案，由用户自行检查并提交。",
                tooltip=(
                    "开启后自动提交测验并读取分数；关闭时只填写答案，"
                    "由你自行检查提交。"
                ),
                is_necessary=False,
            ),
            SettingsFieldSpec(
                key="publish_discussions",
                label="自动发布讨论",
                kind="switch",
                alert=True,
                help="关闭时只复制上一条回复并填入编辑器，不发布。",
                tooltip=(
                    "开启后自动发布讨论回复；关闭时只复制并填入编辑器，"
                    "不发布。"
                ),
                is_necessary=False,
            ),
            SettingsFieldSpec(
                key="answer_ttl_hours",
                label="题库缓存有效期（小时）",
                kind="number",
                min_value=1,
                max_value=168,
                step=1,
                help="超过有效期后后台同步会重新抓取题目。",
                tooltip="题库缓存的保留时长；超过后后台同步会重新抓取题目。",
                is_necessary=False,
            ),
            SettingsFieldSpec(
                key="auto_sync_answers",
                label="自动同步题库",
                kind="switch",
                help="选择课程后在后台同步该课程的答案。",
                tooltip=(
                    "选择课程后在后台自动同步该课程题库；关闭后需手动点"
                    "“同步”。"
                ),
                is_necessary=False,
            ),
            SettingsFieldSpec(
                key="download_documents",
                label="下载课件",
                kind="switch",
                help="刷文档时同时下载 PDF/附件。",
                tooltip=(
                    "刷文档任务时同时下载 PDF/附件到 documents/icourse。"
                ),
                is_necessary=False,
            ),
            SettingsFieldSpec(
                key="retain_data",
                label="留存数据",
                kind="switch",
                alert=True,
                help="关闭后不再自动保存讨论、测验等任务截图。",
                tooltip=(
                    "关闭后不再自动保存讨论、测验等任务截图；"
                    "已有截图不会被删除。"
                ),
                is_necessary=False,
            ),
        )

        def values_getter() -> dict[str, Any]:
            return self._read_settings()

        def exporter(values: dict[str, Any]) -> dict[str, Any]:
            return {"icourse": dict(values)}

        return FeatureSettingsGroup(
            group_id="icourse",
            title=_FEATURE_NAME,
            description="账号、并发、视频倍速与写操作开关。",
            field_specs=specs,
            values_getter=values_getter,
            exporter=exporter,
            complete_checker=lambda: True,
            missing_getter=lambda: [],
            enabled_getter=lambda: is_feature_enabled(_FEATURE_NAME),
            enabled_setter=lambda enabled: set_feature_enabled(_FEATURE_NAME, enabled),
            enabled_editable=True,
        )

    def _read_settings(self) -> dict[str, Any]:
        """读取并规范化慕课配置。

        Returns:
            含全部设置键的字典。
        """
        config_data: Any = load_config().get("icourse")
        source: dict[str, Any] = (
            dict(config_data) if isinstance(config_data, dict) else {}
        )
        values: dict[str, Any] = dict(_DEFAULT_SETTINGS)
        values.update(source)
        values["workers"] = _clamp_workers(values.get("workers"))
        try:
            values["video_rate"] = max(
                1.0, min(2.0, float(values.get("video_rate") or 2.0))
            )
        except (TypeError, ValueError):
            values["video_rate"] = 2.0
        try:
            values["answer_ttl_hours"] = max(
                1, min(168, int(values.get("answer_ttl_hours") or 24))
            )
        except (TypeError, ValueError):
            values["answer_ttl_hours"] = 24
        for key in (
            "submit_quizzes",
            "publish_discussions",
            "auto_sync_answers",
            "download_documents",
            "retain_data",
        ):
            values[key] = bool(values.get(key))
        values["account"] = str(values.get("account") or "").strip()
        values["password"] = str(values.get("password") or "")
        if values.get("account_type") not in ("icourse", "mail", "phone"):
            # 旧配置中的 auto 或未知值统一回退到“爱课程”，由用户再显式修改。
            values["account_type"] = "icourse"
        return {key: values.get(key, _DEFAULT_SETTINGS[key]) for key in _DEFAULT_SETTINGS}

    # ------------------------------------------------------------------ 依赖
    def _db_provider(self) -> Any:
        """返回 IcourseDb provider。

        Returns:
            慕课题库 provider。

        Raises:
            hwklr_db.DbProviderNotFoundError: provider 缺失。
        """
        from hwklr.db.icoursedb import IcourseDb

        provider = hwklr_db.get_db_manager().get(_DB_NAME)
        if not isinstance(provider, IcourseDb):
            raise hwklr_db.DbProviderNotFoundError("未找到慕课题库 provider")
        return provider

    def _catalog_set(self) -> set[int]:
        """返回内置题库目录中的 term id 集合。

        Returns:
            id 集合；目录不可用时为空集合。
        """
        if self._catalog_ids is not None:
            return self._catalog_ids
        try:
            # 目录通过统一的 Feature._load_db 读取，首次访问会缓存到外部 db/icourse0.json。
            payload: dict[str, Any] = self._load_db(0) or {}
            routes: Any = payload.get("items")
            if not isinstance(routes, list):
                routes = self._db_provider().catalog_courses()
            ids: set[int] = set()
            for item in routes:
                if not isinstance(item, dict):
                    continue
                try:
                    ids.add(int(item.get("id")))
                except (TypeError, ValueError):
                    continue
            with self._state_lock:
                self._catalog_ids = ids
            return ids
        except Exception:
            return set()

    def _require_client(self) -> tuple[Any, dict[str, Any]]:
        """加载已登录客户端。

        Returns:
            ``(MoocClient, user)``。

        Raises:
            Exception: 未登录时由 login_service 抛出。
        """
        from . import login_service

        return login_service.load_client(log=lambda message: _LOGGER.info(message))

    def _answer_store(self) -> Any:
        """构造答案适配层。

        Returns:
            :class:`AnswerStore`。
        """
        from .answer_store import AnswerStore

        ttl = self._read_settings()["answer_ttl_hours"] * 3600
        return AnswerStore(self._db_provider(), ttl)

    # ------------------------------------------------------------------ 动作
    def handle(self, action: str, params: dict[str, Any]) -> ApiResult:
        """处理 UI 动作。

        Args:
            action: 动作名。
            params: 参数。

        Returns:
            统一结果字典。
        """
        handlers = {
            "get_state": self._action_get_state,
            "validate_login": self._action_validate_login,
            "load_courses": self._action_load_courses,
            "select_course": self._action_select_course,
            "get_course": self._action_get_course,
            "start_login_job": self._action_start_login_job,
            "get_login_job": self._action_get_login_job,
            "cancel_login_job": self._action_cancel_login_job,
            "logout": self._action_logout,
            "start_answer_sync": self._action_start_answer_sync,
            "get_answer_sync": self._action_get_answer_sync,
            "start_completion_job": self._action_start_completion_job,
            "get_completion_job": self._action_get_completion_job,
            "cancel_completion_job": self._action_cancel_completion_job,
        }
        handler = handlers.get(action)
        if handler is None:
            return failure("未知动作: %s" % action)
        try:
            return handler(params or {})
        except hwklr_db.DbError as exc:
            _LOGGER.warning("慕课数据库错误: %s", exc)
            return failure(str(exc))
        except Exception as exc:  # 兜底，保证错误能回到 UI。
            _LOGGER.exception("慕课功能未预期异常")
            return failure("操作失败: %s" % exc)

    def _action_validate_login(self, params: dict[str, Any]) -> ApiResult:
        """校验当前浏览器登录态；仅在失效时返回 logged_in=False。

        该校验在标签激活时调用，不清理已选课程缓存。
        """
        from . import login_service

        try:
            with self._state_lock:
                member: dict[str, Any] = dict(self._member)
            if not member:
                _client, member = login_service.load_client()
            login_service.ensure_storage_state_valid()
        except Exception as exc:
            _LOGGER.info("慕课登录态校验失败: %s", exc)
            return success({"logged_in": False, "reason": str(exc), "user": {}})
        with self._state_lock:
            self._member = dict(member)
        return success({"logged_in": True, "user": dict(member)})

    def _action_get_state(self, params: dict[str, Any]) -> ApiResult:
        """返回缓存状态，不联网。"""
        with self._state_lock:
            courses = [self._course_summary(course) for course in self._courses]
            course_payload = copy.deepcopy(self._course_payload)
            member = dict(self._member)
        login_job = self._login_job.snapshot()
        with self._answer_sync_lock:
            sync = (
                self._answer_sync.snapshot()
                if self._answer_sync is not None
                else self._idle_answer_sync()
            )
        with self._job_lock:
            job = (
                self._job.snapshot()
                if self._job is not None
                else self._idle_completion()
            )
        saved_user: dict[str, Any] = member or self._saved_user()
        return success(
            {
                "logged_in": bool(saved_user) or self._has_session(),
                "user": saved_user,
                "courses": courses,
                "course": course_payload,
                "login_job": login_job,
                "answer_sync": sync,
                "job": job,
                "settings": self._settings_summary(),
            }
        )

    def _action_load_courses(self, params: dict[str, Any]) -> ApiResult:
        """获取课程列表。"""
        try:
            client, member = self._require_client()
        except Exception as exc:
            return failure(str(exc))
        from .courses import fetch_course_items

        items = fetch_course_items(
            client, spoc_session=config.spoc_session_file()
        )
        built = [build_course_without_tasks(item) for item in items]
        with self._state_lock:
            self._state.replace_courses(items, built, member)
        return success(
            {
                "courses": [self._course_summary(course) for course in built],
                "user": dict(member),
            }
        )

    def _action_select_course(self, params: dict[str, Any]) -> ApiResult:
        """选择课程并构建完整任务树。"""
        term_id = int(params.get("term_id") or 0)
        if term_id <= 0:
            return failure("课程 id 不合法")
        with self._state_lock:
            items = list(self._course_items)
        item = next(
            (entry for entry in items if extract_term_id(entry) == term_id),
            None,
        )
        if item is None:
            self._action_load_courses({})
            with self._state_lock:
                items = list(self._course_items)
            item = next(
                (entry for entry in items if extract_term_id(entry) == term_id),
                None,
            )
        if item is None:
            return failure("未找到课程，请刷新课程列表")

        try:
            client, member = self._require_client()
        except Exception as exc:
            return failure(str(exc))
        from .courses import fetch_term, load_learned_client

        learned = load_learned_client(config.spoc_session_file())
        term = fetch_term(client, learned, term_id)
        course = build_course(term, item)
        self._assign_keys(course)
        catalog_available = term_id in self._catalog_set()
        payload = {
            "course": course.to_dict(True),
            "types": self._type_counts(course),
            "catalog": {
                "available": catalog_available,
                "reason": "" if catalog_available else "题库未收录该课程",
            },
        }
        with self._state_lock:
            self._state.select(course, payload, member)
        if (
            catalog_available
            and self._read_settings()["auto_sync_answers"]
        ):
            test_ids = sorted(
                {
                    int(task.test_id)
                    for task in course.tasks
                    if task.test_id and task.kind in _QUIZ_KINDS
                }
            )
            if test_ids:
                self._start_answer_sync(term_id, test_ids, force=False)
        payload["answer_sync"] = self._action_get_answer_sync({}).get("data", {})
        return success(payload)

    def _action_get_course(self, params: dict[str, Any]) -> ApiResult:
        """返回缓存的课程树。"""
        with self._state_lock:
            payload = copy.deepcopy(self._course_payload)
        if not payload:
            return failure("尚未选择课程")
        payload["answer_sync"] = self._action_get_answer_sync({}).get("data", {})
        return success(payload)

    # ------------------------------------------------------------------ 登录
    def _action_start_login_job(self, params: dict[str, Any]) -> ApiResult:
        """启动登录后台任务。"""
        mode = str(params.get("mode") or "auto").strip().lower()
        if mode not in ("auto", "headless", "visible", "cookies"):
            return failure("登录方式不合法")
        settings = self._read_settings()
        if mode == "headless" and (
            not settings["account"] or not settings["password"]
        ):
            return failure("后台登录需要先在设置中填写账号和密码；也可以使用窗口登录或导入 Cookie")
        if self._login_job.running:
            return failure("已有登录任务正在运行")
        browser = str(params.get("browser") or "auto")
        self._login_job.start(
            lambda job: self._run_login_job(job.job_id, mode, browser),
            initial={
                "phase": "starting",
                "message": "正在准备登录…",
                "error": "",
                "user": {},
            },
        )
        return success({"job_id": self._login_job.job_id, "mode": mode})

    def _run_login_job(self, job_id: str, mode: str, browser: str) -> None:
        """登录线程主体。"""
        from . import login_service

        def log(level: str, message: str) -> None:
            self._append_login_event(job_id, level, message)

        try:
            settings = self._read_settings()
            if mode == "auto":
                self._update_login(
                    job_id, phase="auto", message="正在尝试自动登录…"
                )
                user = self._auto_login(log)
                if user is None:
                    self._update_login(
                        job_id,
                        running=False,
                        done=True,
                        phase="need_visible",
                        message="自动登录失败，需要在弹出的浏览器窗口中登录",
                        error="",
                        user={},
                    )
                    log("warn", "自动登录失败，请选择是否在浏览器窗口中登录")
                    return
            elif mode == "cookies":
                self._update_login(
                    job_id, phase="browser", message="正在导入本机 Cookie…"
                )
                user = login_service.import_browser_cookies(
                    browser=browser, log=lambda m: log("info", m), cancel=self._login_job.cancel_event
                )
            else:
                self._update_login(
                    job_id,
                    phase="browser",
                    message=(
                        "正在后台登录…"
                        if mode == "headless"
                        else "请在浏览器窗口中完成登录…"
                    ),
                )
                user = login_service.login_with_credentials(
                    settings["account"],
                    settings["password"],
                    account_type=settings["account_type"],
                    browser=browser,
                    headless=(mode == "headless"),
                    log=lambda m: log("info", m),
                    cancel=self._login_job.cancel_event,
                )
            if self._login_job.cancel_event.is_set():
                raise RuntimeError("登录已取消")
            with self._state_lock:
                self._state.clear()
                self._member = dict(user)
            self._update_login(
                job_id,
                running=False,
                done=True,
                cancelled=False,
                phase="done",
                message="登录成功",
                error="",
                user=dict(user),
            )
            log("success", "登录成功")
        except Exception as exc:
            self._update_login(
                job_id,
                running=False,
                done=True,
                phase="error",
                message="登录失败",
                error=str(exc),
            )
            log("error", "登录失败：%s" % exc)

    def _auto_login(self, log: Any) -> dict[str, Any] | None:
        """按 Cookie → 本机 Cookie → 设置账号的顺序自动登录。

        Args:
            log: ``(level, message)`` 日志回调。

        Returns:
            登录用户信息；全部失败时返回 ``None``（由 UI 询问窗口登录）。
        """
        from . import login_service

        settings = self._read_settings()

        def say(level: str, message: str) -> None:
            try:
                log(level, message)
            except Exception:
                pass

        def validate(client: Any) -> None:
            client.get_enrolled_courses(include_spoc=True)

        # 1. 已保存的 Cookie/会话。
        try:
            client, user = login_service.load_client(log=lambda m: say("info", m))
            validate(client)
            login_service.ensure_storage_state_valid(log=lambda m: say("info", m))
            say("success", "已使用保存的 Cookie 登录")
            return user
        except Exception as exc:
            say("info", "保存的 Cookie 不可用：%s" % exc)

        # 2. 本机浏览器 Cookie。
        try:
            imported = login_service.import_browser_cookies(
                browser="auto",
                log=lambda m: say("info", m),
                cancel=self._login_job.cancel_event,
            )
            client, user = login_service.load_client(log=lambda m: say("info", m))
            validate(client)
            login_service.ensure_storage_state_valid(log=lambda m: say("info", m))
            say("success", "已导入本机浏览器 Cookie 登录")
            return user or imported
        except Exception as exc:
            say("info", "本机 Cookie 登录失败：%s" % exc)

        # 3. 设置中的账号密码（无头）。
        if settings["account"] and settings["password"]:
            try:
                user = login_service.login_with_credentials(
                    settings["account"],
                    settings["password"],
                    account_type=settings["account_type"],
                    browser="auto",
                    headless=True,
                    log=lambda m: say("info", m),
                    cancel=self._login_job.cancel_event,
                )
                login_service.ensure_storage_state_valid(log=lambda m: say("info", m))
                say("success", "已使用设置中的账号登录")
                return user
            except Exception as exc:
                say("warn", "账号登录失败：%s" % exc)
        return None

    def _update_login(self, job_id: str, **fields: Any) -> None:
        self._login_job.update_if(job_id, **fields)

    def _append_login_event(self, job_id: str, level: str, message: str) -> None:
        if not job_id or self._login_job.job_id != job_id:
            return
        self._login_job.event(level, message)

    def _action_get_login_job(self, params: dict[str, Any]) -> ApiResult:
        """返回登录任务快照。"""
        job_id = str(params.get("job_id") or "")
        snapshot = self._login_job.snapshot()
        if job_id and snapshot.get("job_id") != job_id:
            return failure("登录任务不存在")
        return success(snapshot)

    def _action_cancel_login_job(self, params: dict[str, Any]) -> ApiResult:
        """取消登录任务。"""
        if not self._login_job.running:
            return success({"cancelled": True})
        self._login_job.cancel()
        return success({"cancelled": True})

    def _action_logout(self, params: dict[str, Any]) -> ApiResult:
        """退出登录并清理缓存。"""
        with self._job_lock:
            if self._job is not None and self._job.snapshot().get("running"):
                return failure("任务运行中，暂时不能退出登录")
        if self._login_job.running:
            return failure("登录任务运行中，暂时不能退出登录")
        from . import login_service

        login_service.logout()
        with self._state_lock:
            self._state.clear(clear_catalog=True)
        return success(self._action_get_state({}).get("data", {}))

    # ------------------------------------------------------------------ 题库同步
    def _start_answer_sync(
        self, term_id: int, test_ids: list[int], *, force: bool
    ) -> dict[str, Any]:
        """启动或复用题库同步任务。"""
        from .answer_sync import AnswerSyncJob

        with self._answer_sync_lock:
            current = self._answer_sync
            if current is not None:
                snapshot = current.snapshot()
                if (
                    snapshot.get("running")
                    and snapshot.get("term_id") == term_id
                ):
                    return snapshot
                current.cancel()
                # 避免旧同步线程在新任务落盘后继续写入。
                current.join(1.0)
            job = AnswerSyncJob(
                self._db_provider(),
                term_id,
                test_ids,
                ttl_seconds=self._read_settings()["answer_ttl_hours"] * 3600,
                log=lambda message: _LOGGER.info("慕课题库同步: %s", message),
                force=force,
            )
            self._answer_sync = job
            self._jobs.put("answer_sync", job.background_job)
            job.start()
            return job.snapshot()

    def _action_start_answer_sync(self, params: dict[str, Any]) -> ApiResult:
        """启动题库同步。"""
        with self._state_lock:
            course = self._course
        term_id = int(params.get("term_id") or (course.term_id if course else 0))
        if term_id <= 0:
            return failure("请先选择课程")
        if not (term_id in self._catalog_set()):
            return failure("题库未收录该课程")
        if course is None or course.term_id != term_id:
            return failure("请先重新选择课程")
        test_ids = sorted(
            {
                int(task.test_id)
                for task in course.tasks
                if task.test_id and task.kind in _QUIZ_KINDS
            }
        )
        if not test_ids:
            return failure("该课程没有可同步的测验")
        snapshot = self._start_answer_sync(
            term_id, test_ids, force=bool(params.get("force"))
        )
        return success({"started": True, "sync": snapshot})

    def _action_get_answer_sync(self, params: dict[str, Any]) -> ApiResult:
        """返回题库同步快照。"""
        with self._answer_sync_lock:
            snapshot = (
                self._answer_sync.snapshot()
                if self._answer_sync is not None
                else self._idle_answer_sync()
            )
        return success(snapshot)

    # ------------------------------------------------------------------ 完成任务
    def _action_start_completion_job(self, params: dict[str, Any]) -> ApiResult:
        """启动“开始完成”后台任务。"""
        term_id = int(params.get("term_id") or 0)
        keys = params.get("task_keys")
        if not isinstance(keys, list) or not keys:
            return failure("请先选择任务")
        with self._state_lock:
            course = self._course
        if course is None or course.term_id != term_id:
            return failure("课程已变更，请重新选择课程")
        by_key = {task.key: task for task in course.tasks}
        selected: list[Task] = []
        seen: set[str] = set()
        for key in keys:
            task = by_key.get(str(key))
            if task is None or task.key in seen:
                continue
            seen.add(task.key)
            if task.status == DONE:
                continue
            selected.append(task)
        if not selected:
            return failure("所选任务均已完成")
        with self._job_lock:
            if self._job is not None and self._job.snapshot().get("running"):
                return failure("已有任务正在运行")
            from .job import CompletionJob

            try:
                client, member = self._require_client()
            except Exception as exc:
                return failure(str(exc))
            with self._state_lock:
                self._member = dict(member)
            settings = self._read_settings()
            settings.pop("password", None)
            settings.pop("account", None)
            job = CompletionJob(
                course,
                selected,
                client=client,
                db=self._db_provider(),
                settings=settings,
                log_callback=lambda level, message: _LOGGER.info(
                    "慕课任务[%s] %s", level, message
                ),
            )
            self._job = job
            self._jobs.put("completion", job.background_job)
            snapshot = job.start()
        return success(snapshot)

    def _action_get_completion_job(self, params: dict[str, Any]) -> ApiResult:
        """返回完成任务快照。"""
        job_id = str(params.get("job_id") or "")
        with self._job_lock:
            job = self._job
            if job is None:
                return success(self._idle_completion())
            snapshot = job.snapshot()
            updated = job.updated_course if snapshot.get("done") else None
        if job_id and snapshot.get("job_id") != job_id:
            return failure("任务不存在")
        if updated is not None:
            self._assign_keys(updated)
            payload = {
                "course": updated.to_dict(True),
                "types": self._type_counts(updated),
                "catalog": {
                    "available": updated.term_id in self._catalog_set(),
                    "reason": (
                        ""
                        if updated.term_id in self._catalog_set()
                        else "题库未收录该课程"
                    ),
                },
            }
            with self._state_lock:
                self._state.apply_completion(updated, payload)
        return success(snapshot)

    def _action_cancel_completion_job(self, params: dict[str, Any]) -> ApiResult:
        """取消完成任务。"""
        with self._job_lock:
            job = self._job
        if job is None:
            return success({"cancelled": True})
        job.cancel()
        return success({"cancelled": True})

    # ------------------------------------------------------------------ 辅助
    def _course_summary(self, course: Course) -> dict[str, Any]:
        """构造课程摘要（含题库可用性）。"""
        data = course.to_dict(False)
        available = course.term_id in self._catalog_set()
        data["catalog"] = {
            "available": available,
            "reason": "" if available else "题库未收录该课程",
        }
        return data

    @staticmethod
    def _assign_keys(course: Course) -> None:
        """为课程任务分配唯一 key。"""
        used: dict[str, int] = {}
        for task in course.tasks:
            base = _task_key_base(task)
            used[base] = used.get(base, 0) + 1
            task.key = base if used[base] == 1 else "%s#%d" % (base, used[base])

    @staticmethod
    def _type_counts(course: Course) -> list[dict[str, Any]]:
        """统计各任务类型的数量。"""
        counts: dict[str, dict[str, int]] = {}
        for task in course.tasks:
            entry = counts.setdefault(task.kind, {"total": 0, "pending": 0})
            entry["total"] += 1
            if task.status != DONE:
                entry["pending"] += 1
        ordered: list[str] = [
            kind for kind in _KIND_ORDER if kind in counts
        ] + [kind for kind in counts if kind not in _KIND_ORDER]
        return [
            {
                "kind": kind,
                "total": counts[kind]["total"],
                "pending": counts[kind]["pending"],
            }
            for kind in ordered
        ]

    def _saved_user(self) -> dict[str, Any]:
        """从会话文件读取用户，不发网络请求。"""
        from .session_store import has_login_cookies, load_session

        saved = load_session(config.session_file())
        if saved is None or not has_login_cookies(saved):
            return {}
        return dict(saved.user)

    def _has_session(self) -> bool:
        """判断是否存在带登录 Cookie 的会话文件。

        Returns:
            存在返回 ``True``。
        """
        from .session_store import has_login_cookies, load_session

        return has_login_cookies(load_session(config.session_file()))

    def _settings_summary(self) -> dict[str, Any]:
        """返回可展示的非敏感设置。"""
        settings = self._read_settings()
        settings.pop("password", None)
        settings.pop("account", None)
        return settings

    @staticmethod
    def _idle_login() -> dict[str, Any]:
        """返回空闲登录快照。"""
        return {
            "job_id": "",
            "running": False,
            "done": False,
            "cancelled": False,
            "phase": "idle",
            "message": "",
            "events": [],
            "error": "",
            "user": {},
        }

    @staticmethod
    def _idle_answer_sync() -> dict[str, Any]:
        """返回空闲题库同步快照。"""
        return {
            "running": False,
            "done": False,
            "cancelled": False,
            "term_id": 0,
            "current": 0,
            "total": 0,
            "cached": 0,
            "total_tests": 0,
            "message": "",
            "error": "",
            "started_at": 0.0,
            "finished_at": 0.0,
        }

    @staticmethod
    def _idle_completion() -> dict[str, Any]:
        """返回空闲完成任务快照。"""
        return {
            "job_id": "",
            "running": False,
            "done": False,
            "cancelled": False,
            "phase": "idle",
            "message": "",
            "current": 0,
            "total": 0,
            "term_id": 0,
            "course_name": "",
            "workers": 8,
            "submit_quizzes": False,
            "publish_discussions": False,
            "tasks": [],
            "events": [],
            "result": {"done": 0, "failed": 0, "skipped": 0, "cancelled": 0},
            "error": "",
        }
