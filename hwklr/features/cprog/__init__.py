# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-01 00:01
# 最后更新: 2026-11-12 13:40
# 文件名: __init__.py
# 主要用途: 实现“C程序设计”功能：课程/题目选择、启发模式、题解模式、启用开关与设置板块（依赖延迟加载）。
# 文件版本: 4.6.1
"""C 程序设计功能。

重制自 ``B_CHelper``，主要变化：
- 课程结构直接使用页面“部分”字段本地分组，不再调用 AI（减少调用与 token）；
- 讲解按题目缓存到内存，重复进入不重复调用 AI；
- 所有 AI 输出都要求严格 JSON，并在本地校验字段；
- 题解模式在后台线程运行，UI 轮询进度，不阻塞窗口；
- 提交失败最多 5 次，并把判题错误回传给 AI 修正代码。
"""
from __future__ import annotations

import copy
import logging
import threading
import time
from datetime import datetime
from typing import Any, Final

from hwklr.config import load_config, update_config
from hwklr.contracts import ActionSpec, JobKind
from hwklr.feature_specs import FEATURE_BY_ID
from hwklr.features.about import AboutMetadataGroup, about_meta_from_spec
from hwklr.features.base import ApiResult, Feature, failure, success
from hwklr.features.extensions import is_feature_enabled, set_feature_enabled
from hwklr.features.jobs import BackgroundJob, JobStore
from hwklr.features.settings import FeatureSettingsGroup, SettingsFieldSpec

from .ai import (
    AIClient,
    AIError,
    INITIAL_MAX_TOKENS,
    MAX_OUTPUT_TOKENS,
    analysis_question_info,
    generate_solution,
    next_thinking_level,
)
from .models import (
    Consequence,
    Course,
    CourseStructure,
    Part,
    ProblemDetail,
    ProblemRef,
    QuestionAnalysis,
    SolutionDraft,
)
from .parsers import deterministic_structure
from .site import MoodleError, MoodleSite, SubmitError

__version__ = "4.6.1"
__author__ = "Gary"
__all__ = ["CProgrammingFeature"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_MAX_ATTEMPTS: Final[int] = 5


class SolutionCancelled(Exception):
    """题解任务被用户终止。"""
_MAX_SUBMIT_ERRORS: Final[int] = 3
_MAX_EVENTS: Final[int] = 200
_DEFAULT_CONCURRENCY: Final[int] = 8
_MAX_CONCURRENCY: Final[int] = 8
_THINKING_LABELS: Final[dict[str, str]] = {
    "off": "关闭",
    "low": "低",
    "high": "高",
    "max": "最高",
}
# PE（格式错误）与 CE（编译错误）不提高思考等级，只重新生成代码。
_NO_ESCALATE_STATUSES: Final[tuple[str, ...]] = ("PE", "CE")
_PROVIDER_OPTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("deepseek", "DeepSeek"),
    ("openai", "OpenAI"),
    ("siliconflow", "硅基流动 SiliconFlow"),
    ("local", "本地 OpenAI 兼容服务"),
    ("custom", "自定义 OpenAI 兼容 API"),
)


def _status_code(status: str) -> str:
    """提取判题状态前缀（如 ``WA: Wrong Answer`` → ``WA``）。

    Args:
        status: 判题状态文本。

    Returns:
        大写状态前缀。
    """
    return str(status or "").split(":", 1)[0].strip().upper()


def _clamp_concurrency(value: Any) -> int:
    """把并发数规范化为 1~8 的整数。

    Args:
        value: 配置或前端传入的并发数。

    Returns:
        合法并发数；无法识别时返回默认值 8。
    """
    try:
        number: int = int(value)
    except (TypeError, ValueError):
        return _DEFAULT_CONCURRENCY
    return max(1, min(_MAX_CONCURRENCY, number))


def _split_chunks(items: list[int], count: int) -> list[list[int]]:
    """按顺序把题目平均分成若干连续段。

    余数分配给靠后的线程，例如 10 题 3 线程得到 ``3/3/4``。

    Args:
        items: 按课程顺序排列的题目模块 ID。
        count: 期望的线程数。

    Returns:
        非空的连续分段列表。
    """
    if not items:
        return []
    workers: int = max(1, min(count, len(items)))
    base: int
    remainder: int
    base, remainder = divmod(len(items), workers)
    chunks: list[list[int]] = []
    start: int = 0
    for index in range(workers):
        size: int = base + (1 if index >= workers - remainder else 0)
        if size <= 0:
            continue
        chunks.append(items[start:start + size])
        start += size
    return chunks


def _ai_complete(setting: dict[str, Any]) -> bool:
    """判断 AI 配置是否完整。

    Args:
        setting: C 程序设计 AI 配置。

    Returns:
        配置完整返回 ``True``。
    """
    model: str = str(setting.get("model") or "").strip()
    base_url: str = str(setting.get("base_url") or "").strip()
    api_key: str = str(setting.get("api_key") or "").strip()
    provider: str = str(setting.get("provider") or "custom").lower()
    if not model or not base_url:
        return False
    if provider == "local":
        return True
    return bool(api_key)


class CProgrammingFeature(Feature):
    """“C程序设计”功能。"""

    @classmethod
    def action_specs(cls) -> tuple[ActionSpec, ...]:
        """返回 C 程序设计动作声明。"""
        return (
            ActionSpec("get_state"),
            ActionSpec("get_solution_job"),
            ActionSpec("cancel_solution_job", risk="write"),
            ActionSpec("load_courses"),
            ActionSpec("select_course"),
            ActionSpec("analyze_problem"),
            ActionSpec("submit_problem", risk="write"),
            ActionSpec("start_solution_job", risk="destructive"),
        )

    def __init__(self, universal_param: dict[str, Any]) -> None:
        """初始化功能状态。

        Args:
            universal_param: 窗口层注入的通用参数。
        """
        super().__init__(universal_param)
        # _action_lock 串行化会修改业务状态的 UI 动作；_state_lock 只保护内存字段。
        self._action_lock: threading.Lock = threading.Lock()
        self._state_lock: threading.RLock = threading.RLock()
        self._site: MoodleSite | None = None
        self._logged_in: bool = False
        self._username: str = ""
        self._courses: list[Course] = []
        self._course: Course | None = None
        self._structure: CourseStructure | None = None
        self._details: dict[int, ProblemDetail] = {}
        self._analyses: dict[int, QuestionAnalysis] = {}
        self._last_consequences: dict[int, Consequence] = {}
        self._attempts: dict[int, int] = {}
        self._solutions: dict[int, SolutionDraft] = {}
        self._solution_job: BackgroundJob[None] = BackgroundJob(
            JobKind.SOLUTION,
            self._idle_job(),
            max_events=_MAX_EVENTS,
        )
        self._jobs: JobStore = JobStore()
        self._jobs.put("solution", self._solution_job)
        self._settings_group: FeatureSettingsGroup = self._build_settings_group()

    @property
    def _job_cancel(self) -> threading.Event:
        """返回当前题解任务的协作式取消事件。

        Returns:
            取消事件；测试与内部流程沿用旧属性名。
        """
        return self._solution_job.cancel_event

    def shutdown(self) -> None:
        """窗口关闭时取消并等待题解任务。"""
        super().shutdown()
        self._jobs.cancel_all(timeout=0.5)

    # ------------------------------------------------------------- 共享状态
    def _cached_detail(self, module_id: int) -> ProblemDetail | None:
        """线程安全地读取题目详情缓存。"""
        with self._state_lock:
            return self._details.get(module_id)

    def _cache_detail(self, detail: ProblemDetail) -> None:
        """线程安全地写入题目详情缓存。"""
        with self._state_lock:
            self._details[detail.module_id] = detail

    def _cached_analysis(self, module_id: int) -> QuestionAnalysis | None:
        """线程安全地读取启发式讲解缓存。"""
        with self._state_lock:
            return self._analyses.get(module_id)

    def _cache_analysis(self, module_id: int, analysis: QuestionAnalysis) -> None:
        """线程安全地写入启发式讲解缓存。"""
        with self._state_lock:
            self._analyses[module_id] = analysis

    def _get_attempts(self, module_id: int) -> int:
        """线程安全地读取尝试次数。"""
        with self._state_lock:
            return int(self._attempts.get(module_id, 0))

    def _set_attempts(self, module_id: int, attempts: int) -> None:
        """线程安全地写入尝试次数。"""
        with self._state_lock:
            self._attempts[module_id] = attempts

    def _get_last_consequence(self, module_id: int) -> Consequence | None:
        """线程安全地读取上次判题结果。"""
        with self._state_lock:
            return self._last_consequences.get(module_id)

    def _set_last_consequence(
        self, module_id: int, consequence: Consequence
    ) -> None:
        """线程安全地写入上次判题结果。"""
        with self._state_lock:
            self._last_consequences[module_id] = consequence

    def _cache_solution(self, module_id: int, solution: SolutionDraft) -> None:
        """线程安全地写入题解缓存。"""
        with self._state_lock:
            self._solutions[module_id] = solution

    def _structure_snapshot(self) -> CourseStructure | None:
        """读取当前课程结构引用。"""
        with self._state_lock:
            return self._structure

    def _problem_activity(self, problem: ProblemRef) -> int | None:
        """线程安全地读取题目 activity_id。"""
        with self._state_lock:
            return problem.activity_id

    def _problem_result(self, problem: ProblemRef) -> str:
        """线程安全地读取题目最近判题结果。"""
        with self._state_lock:
            return problem.my_result

    def _set_problem_result(self, problem: ProblemRef, value: str) -> None:
        """线程安全地写入题目最近判题结果。"""
        with self._state_lock:
            problem.my_result = value

    def _set_problem_activity(self, problem: ProblemRef, value: int | None) -> None:
        """线程安全地写入题目 activity_id。"""
        with self._state_lock:
            problem.activity_id = value

    # ------------------------------------------------------------------ 设置
    @property
    def settings_group(self) -> FeatureSettingsGroup:
        """返回 C 程序设计的 AI 设置板块。

        Returns:
            AI 设置组。
        """
        return self._settings_group

    @property
    def about_meta(self) -> AboutMetadataGroup:
        """返回 C 程序设计在“关于”页的元信息。

        Returns:
            插件名、包名、作者与版本。
        """
        return about_meta_from_spec(FEATURE_BY_ID["cprog"], __version__)

    def _build_settings_group(self) -> FeatureSettingsGroup:
        """构建 AI 设置板块。

        Returns:
            含服务商、模型、Key、温度与题解模式开关的设置组。
        """

        def values_getter() -> dict[str, Any]:
            """读取 AI 设置。"""
            config: dict[str, Any] = load_config()
            setting: dict[str, Any] = (
                config.get("c_programming")
                if isinstance(config.get("c_programming"), dict)
                else {}
            )
            return {
                "provider": str(setting.get("provider") or "deepseek"),
                "model": str(setting.get("model") or ""),
                "base_url": str(setting.get("base_url") or ""),
                "api_key": str(setting.get("api_key") or ""),
                "thinking_level": str(setting.get("thinking_level") or "auto"),
                "max_concurrency": _clamp_concurrency(
                    setting.get("max_concurrency", _DEFAULT_CONCURRENCY)
                ),
                "enable_solution_mode": bool(setting.get("enable_solution_mode", True)),
            }

        def exporter(values: dict[str, Any]) -> dict[str, Any]:
            """导出 AI 设置。"""
            return {
                "c_programming": {
                    "provider": str(values.get("provider") or "custom"),
                    "model": str(values.get("model") or ""),
                    "base_url": str(values.get("base_url") or ""),
                    "api_key": str(values.get("api_key") or ""),
                    "thinking_level": str(
                        values.get("thinking_level") or "auto"
                    ),
                    "max_concurrency": _clamp_concurrency(
                        values.get("max_concurrency", _DEFAULT_CONCURRENCY)
                    ),
                    "enable_solution_mode": bool(
                        values.get("enable_solution_mode", True)
                    ),
                }
            }

        def complete_checker() -> bool:
            """检查用户名与 AI 配置。"""
            config: dict[str, Any] = load_config()
            username: str = str(config.get("username") or "").strip()
            setting: dict[str, Any] = (
                config.get("c_programming")
                if isinstance(config.get("c_programming"), dict)
                else {}
            )
            return bool(username and _ai_complete(setting))

        def missing_getter() -> list[str]:
            """列出缺失项。"""
            config: dict[str, Any] = load_config()
            setting: dict[str, Any] = (
                config.get("c_programming")
                if isinstance(config.get("c_programming"), dict)
                else {}
            )
            missing: list[str] = []
            if not str(config.get("username") or "").strip():
                missing.append("通用：用户名")
            if not str(setting.get("model") or "").strip():
                missing.append("C程序设计：模型名称")
            if not str(setting.get("base_url") or "").strip():
                missing.append("C程序设计：API Base URL")
            if (
                str(setting.get("provider") or "custom").lower() != "local"
                and not str(setting.get("api_key") or "").strip()
            ):
                missing.append("C程序设计：API Key")
            return missing

        return FeatureSettingsGroup(
            group_id="c_programming",
            title="C程序设计",
            description=(
                "AI 服务与思考等级配置。建议优先使用启发模式；题解模式会在十分需要"
                "真实实例时直接生成并提交完整代码，请谨慎启用。"
            ),
            field_specs=(
                SettingsFieldSpec(
                    key="provider",
                    label="AI 服务商",
                    kind="select",
                    options=_PROVIDER_OPTIONS,
                    help="本地服务可留空 API Key。",
                    tooltip="选择大模型服务商；本地服务可留空 API Key。",
                ),
                SettingsFieldSpec(
                    key="model",
                    label="模型名称",
                    kind="text",
                    placeholder="例如 deepseek-flash",
                    tooltip=(
                        "填写服务商支持的模型名，例如 deepseek-flash；"
                        "名称错误会导致请求失败。"
                    ),
                ),
                SettingsFieldSpec(
                    key="base_url",
                    label="API Base URL",
                    kind="text",
                    placeholder="例如 https://api.deepseek.com",
                    tooltip="API 服务地址；使用官方服务时保持默认地址即可。",
                ),
                SettingsFieldSpec(
                    key="api_key",
                    label="API Key",
                    kind="password",
                    secret=True,
                    strip=False,
                    alert=True,
                    placeholder="仅保存在本机 config.json",
                    tooltip="服务商提供的 API Key，仅保存在本机；本地服务可留空。",
                ),
                SettingsFieldSpec(
                    key="thinking_level",
                    label="思考等级",
                    kind="select",
                    options=(
                        ("auto", "自动（推荐）"),
                        ("off", "关闭（最快）"),
                        ("low", "低"),
                        ("high", "高"),
                        ("max", "最高"),
                    ),
                    help=(
                        "自动：默认关闭思考；JSON 解析失败时加倍输出上限重试，"
                        "判题出现逻辑失败（如 WA/TLE/MLE/RE）时逐级提高思考等级，"
                        "PE/CE 只重写代码（上限 20000）。仅对 DeepSeek 服务商生效。"
                    ),
                    tooltip=(
                        "控制模型思考等级；自动模式会在解析失败或判题逻辑失败时"
                        "逐级提高。"
                    ),
                ),
                SettingsFieldSpec(
                    key="max_concurrency",
                    label="最大并发数",
                    kind="number",
                    min_value=1,
                    max_value=8,
                    step=1,
                    alert=True,
                    help=(
                        "默认 8（上限，多线程并行解题）。按题目顺序平均分配给"
                        "多个线程同时解题；并发过高可能触发平台或 AI 限流。"
                    ),
                    tooltip=(
                        "同时解题的线程数；大于 1 可加速，但过高可能触发平台或 "
                        "AI 限流。"
                    ),
                ),
                SettingsFieldSpec(
                    key="enable_solution_mode",
                    label="启用题解模式",
                    kind="switch",
                    alert=True,
                    help=(
                        "默认启用，题解模式默认打开。关闭时，C程序设计标签页中的"
                        "题解模式不可选，并显示锁头标志。"
                    ),
                    tooltip=(
                        "默认启用；开启后可在题解模式直接生成并提交完整代码，"
                        "请谨慎使用。"
                    ),
                ),
            ),
            values_getter=values_getter,
            exporter=exporter,
            complete_checker=complete_checker,
            missing_getter=missing_getter,
            enabled_getter=lambda: is_feature_enabled("C程序设计"),
            enabled_setter=lambda enabled: set_feature_enabled("C程序设计", enabled),
            enabled_editable=True,
        )

    # ------------------------------------------------------------------ 分发
    def handle(self, action: str, params: dict[str, Any]) -> ApiResult:
        """分发 C 程序设计动作。

        Args:
            action: 动作名称。
            params: 动作参数。

        Returns:
            统一格式的结果字典。
        """
        if action == "get_solution_job":
            return self._get_solution_job(params)
        if action == "cancel_solution_job":
            return self._cancel_solution_job(params)
        if action == "get_state":
            return self._get_state(params)

        with self._action_lock:
            try:
                self._ensure_no_job()
                if action == "load_courses":
                    return self._load_courses(params)
                if action == "select_course":
                    return self._select_course(params)
                if action == "analyze_problem":
                    return self._analyze_problem(params)
                if action == "submit_problem":
                    return self._submit_problem(params)
                if action == "start_solution_job":
                    return self._start_solution_job(params)
                return failure("未知动作: %s" % action)
            except (MoodleError, AIError, SubmitError, ValueError) as exc:
                _LOGGER.warning("C 程序设计操作失败: %s", exc)
                return failure(str(exc))
            except Exception as exc:  # 兜底，保证错误回传到 UI。
                _LOGGER.exception("C 程序设计未预期异常")
                return failure("操作失败: %s" % exc)

    # ------------------------------------------------------------------ 状态
    @staticmethod
    def _idle_job() -> dict[str, Any]:
        """返回空闲任务状态。

        Returns:
            任务状态字典。
        """
        return {
            "job_id": "",
            "running": False,
            "done": False,
            "phase": "idle",
            "message": "",
            "current": 0,
            "total": 0,
            "title": "",
            "concurrency": _DEFAULT_CONCURRENCY,
            "problems": [],
            "events": [],
            "result": None,
            "error": "",
            "cancelling": False,
        }

    def _job_running(self) -> bool:
        """判断题解后台任务是否正在运行。

        Returns:
            运行中返回 ``True``。
        """
        return self._solution_job.running

    def _ensure_no_job(self) -> None:
        """确保当前没有运行中的后台任务。

        Raises:
            ValueError: 有任务运行中时抛出。
        """
        if self._job_running():
            raise ValueError("题解模式正在运行，请等待完成或稍后再试")

    def _read_username(self) -> str:
        """读取通用用户名。

        Returns:
            用户名。
        """
        config: dict[str, Any] = load_config()
        return str(config.get("username") or "").strip()

    def _read_ai_setting(self) -> dict[str, Any]:
        """读取 AI 配置。

        Returns:
            AI 配置字典。
        """
        config: dict[str, Any] = load_config()
        setting: Any = config.get("c_programming")
        return dict(setting) if isinstance(setting, dict) else {}

    def _solution_mode_enabled(self) -> bool:
        """判断设置中是否启用题解模式。

        Returns:
            启用返回 ``True``。
        """
        return bool(self._read_ai_setting().get("enable_solution_mode", True))

    def _read_max_concurrency(self) -> int:
        """读取并规范化最大并发数。

        Returns:
            1~8 的并发数。
        """
        setting: dict[str, Any] = self._read_ai_setting()
        return _clamp_concurrency(
            setting.get("max_concurrency", _DEFAULT_CONCURRENCY)
        )

    def _get_state(self, params: dict[str, Any]) -> ApiResult:
        """返回登录、AI 与课程状态。

        Args:
            params: 未使用的动作参数。

        Returns:
            状态字典。
        """
        setting: dict[str, Any] = self._read_ai_setting()
        with self._state_lock:
            logged_in: bool = self._logged_in
            courses_loaded: bool = bool(self._courses)
            course_name: str = (
                self._structure.course_name if self._structure else ""
            )
            analysis_cached: int = len(self._analyses)
        return success({
            "logged_in": logged_in,
            "username": self._read_username(),
            "ai_ready": _ai_complete(setting),
            "solution_mode_enabled": self._solution_mode_enabled(),
            "courses_loaded": courses_loaded,
            "course_name": course_name,
            "last_course_id": setting.get("last_course_id"),
            "analysis_cached": analysis_cached,
            "job_running": self._job_running(),
        })

    def _ensure_login(self) -> MoodleSite:
        """确保已登录 CITEL。

        Returns:
            已登录客户端。

        Raises:
            ValueError: 用户名为空时抛出。
            MoodleError: 登录失败时抛出。
        """
        with self._state_lock:
            if self._site is not None and self._logged_in:
                return self._site
        site: MoodleSite = self._create_site()
        username: str = self._read_username()
        with self._state_lock:
            if self._site is not None and self._logged_in:
                return self._site
            self._site = site
            self._logged_in = True
            self._username = username
        return site

    def _create_site(self) -> MoodleSite:
        """创建并登录一个独立的 CITEL 客户端。

        并发解题时每个工作线程使用自己的会话，避免共享 ``requests.Session``。

        Returns:
            已登录客户端。

        Raises:
            ValueError: 用户名为空时抛出。
            MoodleError: 登录失败时抛出。
        """
        username: str = self._read_username()
        if not username:
            raise ValueError("请先在设置中填写用户名")
        site: MoodleSite = MoodleSite()
        ok: bool
        message: str
        ok, message = site.login(username, f"{username}@Bjtu")
        if not ok:
            raise MoodleError(message or "登录 CITEL 失败")
        return site

    def _build_ai(self) -> AIClient:
        """构建 AI 客户端。

        Returns:
            AI 客户端。

        Raises:
            ValueError: AI 配置不完整时抛出。
        """
        setting: dict[str, Any] = self._read_ai_setting()
        if not _ai_complete(setting):
            raise ValueError("请先在设置中完成 C 程序设计 AI 配置")
        return AIClient(setting)

    # ------------------------------------------------------------------ 课程
    def _load_courses(self, params: dict[str, Any]) -> ApiResult:
        """登录并读取课程列表。

        Args:
            params: 未使用的动作参数。

        Returns:
            课程列表与上次课程 ID。
        """
        site: MoodleSite = self._ensure_login()
        courses: list[Course] = site.get_courses()
        with self._state_lock:
            self._courses = courses
            username: str = self._username
        setting: dict[str, Any] = self._read_ai_setting()
        return success({
            "courses": [course.to_payload() for course in courses],
            "last_course_id": setting.get("last_course_id"),
            "username": username,
        })

    def _select_course(self, params: dict[str, Any]) -> ApiResult:
        """读取课程编程题并按页面部分本地分组。

        Args:
            params: 必须包含 ``course_id``。

        Returns:
            课程结构（部分与题目列表）。
        """
        try:
            course_id: int = int(params.get("course_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("课程 ID 无效") from exc
        site: MoodleSite = self._ensure_login()
        with self._state_lock:
            course: Course | None = next(
                (item for item in self._courses if item.id == course_id), None
            )
        if course is None:
            course = Course(id=course_id, name=str(course_id))
        title: str
        title, _html = site.get_course_page(course_id)
        rows = site.get_index_rows(course_id)
        # 关键优化：页面本身已包含部分名，直接本地分组，跳过结构 AI 调用。
        structure: CourseStructure = deterministic_structure(
            rows, title or course.name
        )
        with self._state_lock:
            self._course = course
            self._structure = structure
            self._details.clear()
            self._analyses.clear()
        update_config({"c_programming": {"last_course_id": course.id}})
        payload: dict[str, Any] = structure.to_payload()
        payload["course_id"] = course.id
        return success(payload)

    def _find_problem(self, module_id: int) -> ProblemRef:
        """按模块 ID 查找题目。

        Args:
            module_id: 题目模块 ID。

        Returns:
            题目引用。

        Raises:
            ValueError: 未找到时抛出。
        """
        structure: CourseStructure | None = self._structure_snapshot()
        if structure is None:
            raise ValueError("请先选择课程")
        for part in structure.parts:
            for problem in part.problems:
                if problem.module_id == module_id:
                    return problem
        raise ValueError("未找到题目 module_id=%s" % module_id)

    def _part_of(self, module_id: int) -> Part | None:
        """查找题目所属部分。

        Args:
            module_id: 题目模块 ID。

        Returns:
            所属部分；未找到返回 ``None``。
        """
        structure: CourseStructure | None = self._structure_snapshot()
        if structure is None:
            return None
        for part in structure.parts:
            if any(problem.module_id == module_id for problem in part.problems):
                return part
        return None

    def _ensure_detail(
        self, problem: ProblemRef, site: MoodleSite | None = None
    ) -> ProblemDetail:
        """读取并缓存题目详情。

        Args:
            problem: 题目引用。
            site: 可选的独立客户端；并发线程必须传入自己的会话。

        Returns:
            题目详情。
        """
        detail: ProblemDetail | None = self._cached_detail(problem.module_id)
        if detail is not None:
            return detail
        client: MoodleSite = site or self._ensure_login()
        detail = client.get_problem(problem.module_id)
        if detail.activity_id is not None:
            self._set_problem_activity(problem, detail.activity_id)
        self._cache_detail(detail)
        return detail

    def _is_solved(
        self, problem: ProblemRef, site: MoodleSite | None = None
    ) -> tuple[bool, str]:
        """检查题目是否已经 AC（包含历史提交）。

        Args:
            problem: 题目引用。
            site: 可选的独立客户端；并发线程必须传入自己的会话。

        Returns:
            ``(是否已通过, 说明)``。
        """
        result_text: str = self._problem_result(problem)
        if result_text.startswith("AC"):
            return True, result_text
        if not result_text:
            return False, ""
        client: MoodleSite = site or self._ensure_login()
        try:
            solved: bool
            detail: str
            solved, detail = client.has_any_ac(
                problem.module_id, self._problem_activity(problem)
            )
        except MoodleError:
            return False, result_text
        if solved:
            self._set_problem_result(problem, "AC: Accepted")
        return solved, detail or self._problem_result(problem)

    # ------------------------------------------------------------------ 启发
    def _analyze_problem(self, params: dict[str, Any]) -> ApiResult:
        """生成或读取一道题的启发模式讲解。

        Args:
            params: 包含 ``module_id``，可选 ``refresh``。

        Returns:
            讲解、题目详情与提交状态。
        """
        try:
            module_id: int = int(params.get("module_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("题目 ID 无效") from exc
        refresh: bool = bool(params.get("refresh", False))
        problem: ProblemRef = self._find_problem(module_id)
        detail: ProblemDetail = self._ensure_detail(problem)
        solved: bool
        solved_text: str
        solved, solved_text = self._is_solved(problem)
        if solved:
            attempts_done: int = self._get_attempts(module_id)
            return success({
                "already_solved": True,
                "detail": detail.to_payload(),
                "analysis": None,
                "attempts": attempts_done,
                "remaining": max(0, _MAX_ATTEMPTS - attempts_done),
                "problem": problem.to_payload(),
                "message": solved_text or "该题此前已 AC",
            })
        analysis: QuestionAnalysis | None = self._cached_analysis(module_id)
        cached: bool = analysis is not None and not refresh
        ai_error: str = ""
        if analysis is None or refresh:
            ai: AIClient = self._build_ai()
            part: Part | None = self._part_of(module_id)
            previous: Consequence | None = self._get_last_consequence(module_id)
            structure: CourseStructure | None = self._structure_snapshot()
            try:
                analysis = analysis_question_info(
                    ai,
                    detail,
                    previous=previous if refresh else None,
                    course_name=structure.course_name if structure else "",
                    part_name=part.name if part else "",
                )
                self._cache_analysis(module_id, analysis)
            except AIError as exc:
                # 保持原 CLI 的降级能力：AI 不可用时仍展示题面摘要，允许手动编写代码。
                ai_error = str(exc)
                analysis = QuestionAnalysis(
                    simplified_statement=detail.statement[:2000] or detail.title,
                    input_meaning="请参考题面中的输入说明。",
                    test_data_range="请参考题面与公开测试用例。",
                    sample_io="（AI 暂时不可用，请参考题面示例）",
                    logic="（AI 暂时不可用）",
                    precautions=(
                        "AI 分析失败：%s。你仍然可以对照题面编写代码并在"
                        "“大功告成”步骤提交。" % exc
                    ),
                )
        attempts_done = self._get_attempts(module_id)
        return success({
            "already_solved": False,
            "detail": detail.to_payload(),
            "analysis": analysis.to_payload(),
            "attempts": attempts_done,
            "remaining": max(0, _MAX_ATTEMPTS - attempts_done),
            "problem": problem.to_payload(),
            "cached": cached,
            "ai_error": ai_error,
        })

    # ------------------------------------------------------------------ 提交
    def _submit_problem(self, params: dict[str, Any]) -> ApiResult:
        """提交一道题的代码并等待判题结果。

        Args:
            params: 包含 ``module_id`` 与 ``code``。

        Returns:
            判题结果、已用次数与是否可重试。
        """
        try:
            module_id: int = int(params.get("module_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("题目 ID 无效") from exc
        code: str = str(params.get("code") or "")
        if not code.strip():
            raise ValueError("提交代码不能为空")
        problem: ProblemRef = self._find_problem(module_id)
        detail: ProblemDetail = self._ensure_detail(problem)
        activity_id: int | None = self._problem_activity(problem)
        if activity_id is None:
            if detail.activity_id is None:
                raise ValueError("无法确定该题的提交编号")
            activity_id = detail.activity_id
            self._set_problem_activity(problem, activity_id)
        attempts: int = self._get_attempts(module_id)
        if attempts >= _MAX_ATTEMPTS:
            raise ValueError("本题已达到 5 次提交上限")
        site: MoodleSite = self._ensure_login()
        submit_id: int | None = site.submit(activity_id, code, "gcc")
        attempts += 1
        self._set_attempts(module_id, attempts)
        consequence: Consequence = site.poll_consequence(
            activity_id, submit_id, timeout=150.0
        )
        self._set_last_consequence(module_id, consequence)
        self._set_problem_result(
            problem,
            "AC: Accepted" if consequence.is_ac else consequence.status,
        )
        payload: dict[str, Any] = {
            "consequence": consequence.to_payload(),
            "attempts": attempts,
            "remaining": max(0, _MAX_ATTEMPTS - attempts),
            "is_ac": consequence.is_ac,
            "can_retry": attempts < _MAX_ATTEMPTS,
            "problem": problem.to_payload(),
        }
        return success(payload)

    # ------------------------------------------------------------------ 题解
    def _push_event(self, job_id: str, message: str, level: str = "info") -> None:
        """向任务日志追加一条事件。

        Args:
            job_id: 任务 ID。
            message: 事件文本。
            level: 级别（info/success/error/warn）。
        """
        event: dict[str, str] = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "message": message,
            "level": level,
        }

        def append(snapshot: dict[str, Any]) -> None:
            """在 job 锁内追加事件并裁剪长度。"""
            events: list[dict[str, str]] = snapshot.setdefault("events", [])
            events.append(event)
            if len(events) > _MAX_EVENTS:
                del events[: len(events) - _MAX_EVENTS]

        self._solution_job.mutate_if(job_id, append)

    def _update_job(self, job_id: str, **fields: Any) -> None:
        """更新任务状态。

        Args:
            job_id: 任务 ID。
            **fields: 要更新的字段。
        """
        self._solution_job.update_if(job_id, **fields)

    def _start_solution_job(self, params: dict[str, Any]) -> ApiResult:
        """启动题解模式后台任务。

        Args:
            params: 包含 ``module_ids`` 列表。

        Returns:
            任务 ID。
        """
        raw_ids: Any = params.get("module_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise ValueError("请选择至少一道题目")
        module_ids: list[int] = []
        seen: set[int] = set()
        for raw in raw_ids:
            try:
                module_id: int = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("题目 ID 列表格式错误") from exc
            if module_id not in seen:
                seen.add(module_id)
                module_ids.append(module_id)
        if not self._solution_mode_enabled():
            raise ValueError("题解模式未启用，请先在设置中开启")
        if not _ai_complete(self._read_ai_setting()):
            raise ValueError("请先在设置中完成 C 程序设计 AI 配置")
        structure: CourseStructure | None = self._structure_snapshot()
        if structure is None:
            raise ValueError("请先选择课程")

        # 步骤 1：按课程顺序排列题目，便于并发时按顺序连续分段。
        order: dict[int, int] = {}
        for part in structure.parts:
            for problem in part.problems:
                order[problem.module_id] = len(order)
        module_ids.sort(key=lambda item: order.get(item, 10**9))

        # 步骤 2：生成每个题目的实时状态，供前端立即显示“等待队列”。
        problem_states: list[dict[str, Any]] = []
        for module_id in module_ids:
            problem: ProblemRef = self._find_problem(module_id)
            problem_states.append({
                "module_id": module_id,
                "title": problem.title,
                "status": "等待队列",
                "attempts": 0,
                "worker": None,
            })
        concurrency: int = self._read_max_concurrency()
        snapshot: dict[str, Any] = self._solution_job.start(
            lambda job: self._run_solution_job(job.job_id, module_ids),
            initial={
                "phase": "starting",
                "message": "准备题解模式...",
                "total": len(module_ids),
                "concurrency": concurrency,
                "problems": problem_states,
            },
        )
        return success({
            "job_id": str(snapshot.get("job_id") or ""),
            "concurrency": concurrency,
            "problems": copy.deepcopy(problem_states),
        })

    def _get_solution_job(self, params: dict[str, Any]) -> ApiResult:
        """读取题解任务状态。

        Args:
            params: 可包含 ``job_id``。

        Returns:
            任务状态副本。
        """
        requested: str = str(params.get("job_id") or "")
        job: dict[str, Any] = self._solution_job.snapshot()
        if requested and job.get("job_id") != requested:
            return failure("任务不存在或已过期")
        return success(job)

    def _cancel_solution_job(self, params: dict[str, Any]) -> ApiResult:
        """终止当前题解任务。

        Args:
            params: 可包含 ``job_id``。

        Returns:
            终止结果。
        """
        requested: str = str(params.get("job_id") or "")
        snapshot: dict[str, Any] = self._solution_job.snapshot()
        if not snapshot.get("running"):
            return success({"cancelled": False})
        if requested and snapshot.get("job_id") != requested:
            return failure("任务不存在或已过期")
        job_id: str = str(snapshot.get("job_id") or "")
        self._solution_job.update_if(
            job_id,
            cancelling=True,
            message="正在终止解题…",
        )
        self._solution_job.cancel_event.set()
        self._push_event(
            job_id,
            "用户请求终止解题，正在等待当前步骤结束…",
            "warn",
        )
        return success({"cancelled": True})

    def _set_problem_status(
        self,
        job_id: str,
        module_id: int,
        status: str,
        attempts: int | None = None,
        worker: int | None = None,
    ) -> None:
        """更新单个题目的实时状态。

        Args:
            job_id: 任务 ID。
            module_id: 题目模块 ID。
            status: 展示给前端的短状态。
            attempts: 当前尝试次数；``None`` 表示不更新。
            worker: 处理该题的线程序号（从 0 开始）；``None`` 表示不更新。
        """
        def update(snapshot: dict[str, Any]) -> None:
            """在 job 锁内更新目标题目的状态。"""
            for item in snapshot.get("problems", []):
                if item.get("module_id") == module_id:
                    item["status"] = status
                    if attempts is not None:
                        item["attempts"] = attempts
                    if worker is not None:
                        item["worker"] = worker
                    break

        self._solution_job.mutate_if(job_id, update)

    def _complete_problem(self, job_id: str, title: str) -> None:
        """标记一道题处理完成并更新进度。

        Args:
            job_id: 任务 ID。
            title: 完成的题目名称。
        """
        def update(snapshot: dict[str, Any]) -> None:
            """在 job 锁内推进完成计数。"""
            total: int = int(snapshot.get("total") or 0)
            current: int = min(int(snapshot.get("current") or 0) + 1, total)
            snapshot["current"] = current
            snapshot["title"] = title
            snapshot["message"] = f"已完成 {current}/{total} 题"

        self._solution_job.mutate_if(job_id, update)

    def _solve_problem(
        self,
        job_id: str,
        module_id: int,
        site: MoodleSite,
        ai: AIClient,
        worker: int,
    ) -> dict[str, Any]:
        """处理一道题：生成思路、生成题解、提交并按判题结果修正。

        Args:
            job_id: 任务 ID。
            module_id: 题目模块 ID。
            site: 该线程独立的 CITEL 客户端。
            ai: 该线程独立的 AI 客户端。
            worker: 线程序号（从 0 开始）。

        Returns:
            ``{"kind": "ac"/"failed"/"already", "data": {...}}``。
        """
        if self._job_cancel.is_set():
            raise SolutionCancelled()
        problem: ProblemRef = self._find_problem(module_id)
        solved: bool
        solved_text: str
        solved, solved_text = self._is_solved(problem, site=site)
        if solved:
            self._set_problem_status(job_id, module_id, "AC", attempts=0, worker=worker)
            self._push_event(job_id, f"跳过已通过：{problem.title}", "success")
            return {
                "kind": "already",
                "data": {
                    "module_id": problem.module_id,
                    "title": problem.title,
                    "message": solved_text or "此前已 AC",
                },
            }

        detail: ProblemDetail = self._ensure_detail(problem, site=site)
        part: Part | None = self._part_of(module_id)
        part_name: str = part.name if part else ""
        # 每题独立状态：自动模式从“关闭思考 + 5000 输出上限”开始。
        level: str = ai.resolve_thinking_level()
        budget: int = INITIAL_MAX_TOKENS
        analysis: QuestionAnalysis | None = self._cached_analysis(module_id)
        previous: Consequence | None = None
        attempts: int = self._get_attempts(module_id)
        submit_errors: int = 0
        failure_record: dict[str, Any] | None = None
        structure: CourseStructure | None = self._structure_snapshot()

        self._set_problem_status(
            job_id, module_id, "生成题解", attempts=attempts, worker=worker
        )
        self._push_event(
            job_id,
            f"开始解题：{problem.title}"
            f"（线程 {worker + 1}，思考：{_THINKING_LABELS.get(level, level)}）",
            "info",
        )

        while attempts < _MAX_ATTEMPTS:
            if self._job_cancel.is_set():
                raise SolutionCancelled()
            # 步骤 1：需要时生成思路；判题逻辑失败后会置空以更高等级重析。
            if analysis is None:
                self._set_problem_status(
                    job_id, module_id, "生成题解", attempts=attempts, worker=worker
                )
                try:
                    analysis = analysis_question_info(
                        ai,
                        detail,
                        previous=previous,
                        course_name=(
                            structure.course_name if structure else ""
                        ),
                        part_name=part_name,
                        max_tokens=budget,
                        thinking_level=level,
                    )
                except AIError as exc:
                    failure_record = {
                        "module_id": problem.module_id,
                        "title": problem.title,
                        "status": "AI_ERROR",
                        "summary": str(exc),
                        "compile_message": "",
                        "attempts": attempts,
                    }
                    self._set_problem_status(
                        job_id, module_id, "AI错误", attempts=attempts, worker=worker
                    )
                    self._push_event(
                        job_id, f"生成思路失败：{problem.title} - {exc}", "error"
                    )
                    break
                self._cache_analysis(module_id, analysis)
                self._push_event(
                    job_id,
                    f"思路已生成：{problem.title}"
                    f"（思考：{_THINKING_LABELS.get(level, level)}）",
                    "info",
                )

            # 步骤 2：生成题解。
            attempts += 1
            self._set_problem_status(
                job_id, module_id, "生成题解", attempts=attempts, worker=worker
            )
            try:
                solution: SolutionDraft = generate_solution(
                    ai,
                    detail,
                    analysis,
                    previous=previous,
                    max_tokens=budget,
                    thinking_level=level,
                )
            except AIError as exc:
                failure_record = {
                    "module_id": problem.module_id,
                    "title": problem.title,
                    "status": "AI_ERROR",
                    "summary": str(exc),
                    "compile_message": "",
                    "attempts": attempts - 1,
                }
                self._set_problem_status(
                    job_id,
                    module_id,
                    f"AI错误：第{attempts}次尝试",
                    attempts=attempts - 1,
                    worker=worker,
                )
                self._push_event(
                    job_id, f"生成题解失败：{problem.title} - {exc}", "error"
                )
                break
            self._cache_solution(module_id, solution)

            # 关键步骤：提交前确保 activity_id 已解析。
            activity_id: int | None = self._problem_activity(problem)
            if activity_id is None:
                activity_id = site.resolve_activity_id(module_id)
                self._set_problem_activity(problem, activity_id)
            if activity_id is None:
                failure_record = {
                    "module_id": problem.module_id,
                    "title": problem.title,
                    "status": "NO_ACTIVITY_ID",
                    "summary": "无法确定该题的提交编号",
                    "compile_message": "",
                    "attempts": attempts - 1,
                }
                self._set_problem_status(
                    job_id, module_id, "无法提交", attempts=attempts - 1, worker=worker
                )
                self._push_event(
                    job_id, f"无法提交：{problem.title}（缺少 activity_id）", "error"
                )
                break

            # 步骤 3：提交并等待判题。
            if self._job_cancel.is_set():
                raise SolutionCancelled()
            self._set_problem_status(
                job_id, module_id, "提交中", attempts=attempts, worker=worker
            )
            try:
                submit_id: int | None = site.submit(
                    activity_id, solution.code, "gcc"
                )
            except SubmitError as exc:
                submit_errors += 1
                attempts -= 1  # 被拒绝的提交不消耗次数。
                self._push_event(
                    job_id, f"提交被拒绝：{problem.title} - {exc}", "warn"
                )
                if submit_errors >= _MAX_SUBMIT_ERRORS:
                    failure_record = {
                        "module_id": problem.module_id,
                        "title": problem.title,
                        "status": "SUBMIT_REJECTED",
                        "summary": str(exc),
                        "compile_message": "",
                        "attempts": attempts,
                    }
                    self._set_problem_status(
                        job_id, module_id, "提交失败", attempts=attempts, worker=worker
                    )
                    break
                time.sleep(1.0)
                continue

            self._set_attempts(module_id, attempts)
            consequence: Consequence = site.poll_consequence(
                activity_id, submit_id, timeout=150.0
            )
            if self._job_cancel.is_set():
                raise SolutionCancelled()
            self._set_last_consequence(module_id, consequence)
            self._set_problem_result(
                problem,
                "AC: Accepted" if consequence.is_ac else consequence.status,
            )
            if consequence.is_ac:
                self._set_problem_status(
                    job_id, module_id, "AC", attempts=attempts, worker=worker
                )
                ac_record: dict[str, Any] = {
                    "module_id": problem.module_id,
                    "title": problem.title,
                    "solution_title": solution.solution_title,
                    "explanation": solution.explanation,
                    "code": solution.code,
                    "notes": solution.notes,
                    "attempts": attempts,
                }
                self._push_event(
                    job_id, f"AC：{problem.title}（第 {attempts} 次）", "success"
                )
                return {"kind": "ac", "data": ac_record}

            # 步骤 4：未通过。PE/CE 只重写代码；其他失败按自动规则升级。
            previous = consequence
            status_code: str = _status_code(consequence.status) or "错误"
            self._set_problem_status(
                job_id,
                module_id,
                f"{status_code}：第{attempts}次尝试",
                attempts=attempts,
                worker=worker,
            )
            self._push_event(
                job_id,
                f"{problem.title} 第 {attempts} 次未通过：{consequence.status}",
                "warn",
            )
            if status_code in _NO_ESCALATE_STATUSES:
                self._push_event(
                    job_id,
                    f"{problem.title} 为 {status_code}，不提高思考等级与"
                    "输出上限，仅重新生成解答代码",
                    "info",
                )
                continue
            if ai.auto_thinking:
                old_level: str = level
                old_budget: int = budget
                level = next_thinking_level(level)
                budget = min(budget * 2, MAX_OUTPUT_TOKENS)
                if level != old_level or budget != old_budget:
                    self._push_event(
                        job_id,
                        f"{problem.title} 判题失败，思考等级 "
                        f"{_THINKING_LABELS.get(old_level, old_level)} → "
                        f"{_THINKING_LABELS.get(level, level)}，输出上限 "
                        f"{old_budget} → {budget}",
                        "info",
                    )
            # 逻辑失败后带上判题反馈重新分析（PE/CE 保持原思路）。
            analysis = None

        if failure_record is None:
            last: Consequence | None = self._get_last_consequence(module_id)
            recorded_attempts: int = self._get_attempts(module_id)
            failure_record = {
                "module_id": problem.module_id,
                "title": problem.title,
                "status": last.status if last else "FAILED",
                "summary": last.summary if last else "",
                "compile_message": last.compile_message if last else "",
                "attempts": recorded_attempts,
            }
            self._set_problem_status(
                job_id,
                module_id,
                "错误：尝试次数过多",
                attempts=recorded_attempts,
                worker=worker,
            )
        self._push_event(
            job_id,
            f"失败：{problem.title}（{failure_record.get('status', 'FAILED')}）",
            "error",
        )
        return {"kind": "failed", "data": failure_record}

    def _run_solution_job(self, job_id: str, module_ids: list[int]) -> None:
        """后台执行题解模式：按并发数分段，各线程逐题“思考一题、提交一题”。

        自动思考模式下，WA/TLE/MLE/RE 等逻辑失败会把思考等级提高一级并把
        输出预算翻倍；PE/CE 不提高等级与预算，只重新生成代码。

        Args:
            job_id: 任务 ID。
            module_ids: 已按课程顺序排列的题目模块 ID。
        """
        ac_list: list[dict[str, Any]] = []
        failed_list: list[dict[str, Any]] = []
        already_list: list[dict[str, Any]] = []
        cancelled_list: list[dict[str, Any]] = []
        try:
            total: int = len(module_ids)
            concurrency: int = self._read_max_concurrency()
            chunks: list[list[int]] = _split_chunks(module_ids, concurrency)
            workers: int = len(chunks)
            self._update_job(
                job_id,
                phase="solution",
                total=total,
                current=0,
                concurrency=workers,
                message=f"开始解题：{total} 题，{workers} 线程",
            )
            self._push_event(
                job_id, f"启动 {workers} 个解题线程，共 {total} 题", "info"
            )

            # 步骤 1：只登录一次，再把登录 Cookie 克隆给各线程。
            # 同一账号重复登录会让平台使旧会话失效，导致只有最后一个线程能正常访问。
            base_site: MoodleSite = self._ensure_login()
            if self._job_cancel.is_set():
                raise SolutionCancelled()
            contexts: list[tuple[MoodleSite, AIClient]] = []
            for _ in range(workers):
                contexts.append((base_site.clone(), self._build_ai()))

            # 步骤 2：线程按连续分段处理题目。
            outcomes: list[dict[str, Any]] = []
            outcomes_lock: threading.Lock = threading.Lock()

            def worker(
                worker_index: int,
                chunk: list[int],
                site: MoodleSite,
                ai: AIClient,
            ) -> None:
                """处理一个连续题目分段。"""
                for module_id in chunk:
                    if self._job_cancel.is_set():
                        try:
                            title = self._find_problem(module_id).title
                        except Exception:
                            title = str(module_id)
                        self._set_problem_status(
                            job_id, module_id, "已取消", worker=worker_index
                        )
                        with outcomes_lock:
                            outcomes.append({
                                "kind": "cancelled",
                                "data": {
                                    "module_id": module_id,
                                    "title": title,
                                    "status": "CANCELLED",
                                    "summary": "用户终止解题",
                                },
                            })
                        self._complete_problem(job_id, title)
                        continue
                    try:
                        outcome: dict[str, Any] = self._solve_problem(
                            job_id, module_id, site, ai, worker_index
                        )
                    except SolutionCancelled:
                        try:
                            title = self._find_problem(module_id).title
                        except Exception:
                            title = str(module_id)
                        self._set_problem_status(
                            job_id, module_id, "已取消", worker=worker_index
                        )
                        outcome = {
                            "kind": "cancelled",
                            "data": {
                                "module_id": module_id,
                                "title": title,
                                "status": "CANCELLED",
                                "summary": "用户终止解题",
                            },
                        }
                    except Exception as exc:  # 单题异常不拖垮整个线程。
                        _LOGGER.exception(
                            "解题线程 %s 处理题目 %s 失败",
                            worker_index + 1,
                            module_id,
                        )
                        try:
                            title: str = self._find_problem(module_id).title
                        except Exception:
                            title = str(module_id)
                        failed_attempts: int = self._get_attempts(module_id)
                        self._set_problem_status(
                            job_id,
                            module_id,
                            "错误：内部异常",
                            attempts=failed_attempts,
                            worker=worker_index,
                        )
                        outcome = {
                            "kind": "failed",
                            "data": {
                                "module_id": module_id,
                                "title": title,
                                "status": "ERROR",
                                "summary": str(exc),
                                "compile_message": "",
                                "attempts": failed_attempts,
                            },
                        }
                    with outcomes_lock:
                        outcomes.append(outcome)
                    data: Any = outcome.get("data")
                    title_text: str = (
                        str(data.get("title") or "")
                        if isinstance(data, dict)
                        else ""
                    )
                    self._complete_problem(job_id, title_text)

            if workers <= 1:
                worker(0, chunks[0], contexts[0][0], contexts[0][1])
            else:
                threads: list[threading.Thread] = []
                for index, chunk in enumerate(chunks):
                    thread: threading.Thread = threading.Thread(
                        target=worker,
                        args=(index, chunk, contexts[index][0], contexts[index][1]),
                        name=f"CSolutionWorker{index + 1}",
                        daemon=True,
                    )
                    thread.start()
                    threads.append(thread)
                for thread in threads:
                    thread.join()

            # 步骤 3：汇总各线程结果。
            for outcome in outcomes:
                kind: str = str(outcome.get("kind") or "failed")
                data: Any = outcome.get("data")
                payload: dict[str, Any] = data if isinstance(data, dict) else {}
                if kind == "ac":
                    ac_list.append(payload)
                elif kind == "already":
                    already_list.append(payload)
                elif kind == "cancelled":
                    cancelled_list.append(payload)
                else:
                    failed_list.append(payload)

            result: dict[str, Any] = {
                "ac": ac_list,
                "failed": failed_list,
                "already_ac": already_list,
                "cancelled": cancelled_list,
                "selected": len(module_ids),
            }
            if self._job_cancel.is_set():
                self._update_job(
                    job_id,
                    running=False,
                    done=True,
                    phase="cancelled",
                    message="解题已终止",
                    result=result,
                )
                self._push_event(
                    job_id,
                    f"解题已终止：AC {len(ac_list)} 题，失败 {len(failed_list)} 题，"
                    f"取消 {len(cancelled_list)} 题。",
                    "warn",
                )
            else:
                self._update_job(
                    job_id,
                    running=False,
                    done=True,
                    phase="done",
                    message="题解模式完成",
                    result=result,
                )
                self._push_event(
                    job_id,
                    f"完成：AC {len(ac_list)} 题，失败 {len(failed_list)} 题，"
                    f"此前已通过 {len(already_list)} 题。",
                    "success",
                )
        except SolutionCancelled:
            for module_id in module_ids:
                self._set_problem_status(job_id, module_id, "已取消")
            self._update_job(
                job_id,
                running=False,
                done=True,
                phase="cancelled",
                message="解题已终止",
                result={
                    "ac": ac_list,
                    "failed": failed_list,
                    "already_ac": already_list,
                    "cancelled": cancelled_list,
                    "selected": len(module_ids),
                },
            )
            self._push_event(job_id, "解题已终止", "warn")
        except Exception as exc:  # 任务级兜底，确保 UI 能收到错误。
            _LOGGER.exception("题解模式任务失败")
            self._update_job(
                job_id,
                running=False,
                done=True,
                phase="error",
                error=str(exc),
                message="题解模式失败：%s" % exc,
            )
            self._push_event(job_id, "任务失败：%s" % exc, "error")
