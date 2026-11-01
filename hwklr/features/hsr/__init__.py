# -*- coding: utf-8 -*-
# 作者: PhiloK (Remaster by Gary)
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-01 10:21
# 文件名: __init__.py
# 主要用途: 实现“高铁纵横”功能：登录、考试列表、自动答题与提交，并注册密码设置板块。
# 文件版本: 2.0.2
"""高铁纵横功能实现。

原作者 PhiloK（``B1.0/``）；本文件是 Gary 的 Remaster 实现。
保留原有登录、验证码、考试列表、自动匹配答案、
提交并显示得分的全部行为，同时把阻塞操作放到 pywebview 的桥接线程中执行，
避免阻塞 UI。
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any, Final

from hwklr import runtime_data
from hwklr.config import load_config, update_config
from hwklr.features.base import ApiResult, Feature, failure, success
from hwklr.features.settings import FeatureSettingsGroup, SettingsFieldSpec

from .bank import Bank
from .client import HsrApiError, HsrClient

__version__ = "2.0.2"
__author__ = "PhiloK (Remaster by Gary)"
__all__ = ["HSRFeature"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_DATE_FORMATS: Final[tuple[str, ...]] = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")
_BANK_FEATURE_KEY: Final[str] = "hsr"


class HSRFeature(Feature):
    """“高铁纵横”功能。

    通过 :meth:`handle` 暴露给 UI 的动作：
    ``get_state``、``login``、``login_saved``、``logout``、
    ``list_exams``、``start_exam``、``get_bank_info``。
    """

    def __init__(self, universal_param: dict[str, Any]) -> None:
        """初始化题库与登录会话。

        Args:
            universal_param: 窗口层注入的通用参数。
        """
        super().__init__(universal_param)
        # 内置知识库固定从 runtime_data 读取，不在运行时依赖 B1.0 目录。
        self._bank: Bank = Bank(list(runtime_data.load_bank(_BANK_FEATURE_KEY)))
        self._client: HsrClient | None = None
        self._records: list[dict[str, Any]] = []
        self._last_exam: dict[str, Any] | None = None
        self._lock: threading.RLock = threading.RLock()
        self._settings_group: FeatureSettingsGroup = self._build_settings_group()

    @property
    def settings_group(self) -> FeatureSettingsGroup:
        """返回高铁纵横的设置板块（密码）。

        Returns:
            含密码字段的设置组。
        """
        return self._settings_group

    def _build_settings_group(self) -> FeatureSettingsGroup:
        """构建高铁纵横设置板块。

        Returns:
            密码设置组。
        """

        def values_getter() -> dict[str, Any]:
            """读取高铁密码。"""
            config: dict[str, Any] = load_config()
            hsr: dict[str, Any] = (
                config.get("hsr") if isinstance(config.get("hsr"), dict) else {}
            )
            password: str = str(hsr.get("password") or config.get("password") or "")
            return {"password": password}

        def exporter(values: dict[str, Any]) -> dict[str, Any]:
            """导出高铁密码。"""
            return {"hsr": {"password": str(values.get("password") or "")}}

        def complete_checker() -> bool:
            """检查用户名与密码是否都已填写。"""
            config: dict[str, Any] = load_config()
            hsr: dict[str, Any] = (
                config.get("hsr") if isinstance(config.get("hsr"), dict) else {}
            )
            username: str = str(config.get("username") or "").strip()
            password: str = str(hsr.get("password") or config.get("password") or "")
            return bool(username and password)

        def missing_getter() -> list[str]:
            """列出缺失项。"""
            config: dict[str, Any] = load_config()
            hsr: dict[str, Any] = (
                config.get("hsr") if isinstance(config.get("hsr"), dict) else {}
            )
            missing: list[str] = []
            if not str(config.get("username") or "").strip():
                missing.append("通用：用户名")
            if not str(hsr.get("password") or config.get("password") or ""):
                missing.append("高铁纵横：密码")
            return missing

        return FeatureSettingsGroup(
            group_id="hsr",
            title="高铁纵横",
            description="登录高铁答题系统所需的密码；用户名在“通用”中共享。",
            field_specs=(
                SettingsFieldSpec(
                    key="password",
                    label="密码",
                    kind="password",
                    secret=True,
                    strip=False,
                    placeholder="请输入高铁答题系统密码",
                    help="只保存在本机 config.json。",
                ),
            ),
            values_getter=values_getter,
            exporter=exporter,
            complete_checker=complete_checker,
            missing_getter=missing_getter,
        )

    def handle(self, action: str, params: dict[str, Any]) -> ApiResult:
        """分发 UI 动作。

        Args:
            action: 动作名称。
            params: 动作参数。

        Returns:
            统一格式的结果字典；异常会转换为可读错误信息。
        """
        handlers: dict[str, Callable[[dict[str, Any]], ApiResult]] = {
            "get_state": self._action_get_state,
            "login": self._action_login,
            "login_saved": self._action_login_saved,
            "logout": self._action_logout,
            "list_exams": self._action_list_exams,
            "start_exam": self._action_start_exam,
            "get_bank_info": self._action_get_bank_info,
        }
        with self._lock:
            handler: Callable[[dict[str, Any]], ApiResult] | None = handlers.get(action)
            if handler is None:
                return failure("未知动作: %s" % action)
            try:
                return handler(params)
            except HsrApiError as exc:
                _LOGGER.warning("高铁接口调用失败: %s", exc)
                return failure(str(exc))
            except ValueError as exc:
                return failure(str(exc))
            except Exception as exc:  # 兜底，保证错误能回传到 UI。
                _LOGGER.exception("高铁功能未预期异常")
                return failure("操作失败: %s" % exc)

    # ------------------------------------------------------------------ 状态
    @staticmethod
    def _read_credentials() -> tuple[str, str]:
        """从配置读取高铁账号与密码。

        Returns:
            ``(username, password)``。
        """
        config: dict[str, Any] = load_config()
        hsr: dict[str, Any] = (
            config.get("hsr") if isinstance(config.get("hsr"), dict) else {}
        )
        return (
            str(config.get("username") or "").strip(),
            str(hsr.get("password") or config.get("password") or ""),
        )

    def _action_get_state(self, params: dict[str, Any]) -> ApiResult:
        """返回当前登录状态与题库概况。

        Args:
            params: 未使用的动作参数。

        Returns:
            包含 ``logged_in``、``username``、``has_credentials`` 等字段的结果。
        """
        username, password = self._read_credentials()
        chapters: list[str] = []
        for item in self._bank.items:
            chapter: str = str(item.get("chapter") or "")
            if chapter and chapter not in chapters:
                chapters.append(chapter)
        return success({
            "logged_in": self._is_logged_in(),
            "username": username,
            "has_credentials": bool(username and password),
            "bank_count": self._bank.count,
            "bank_chapters": chapters,
        })

    def _is_logged_in(self) -> bool:
        """判断当前是否持有有效 Token。

        Returns:
            已登录返回 ``True``。
        """
        return self._client is not None and bool(self._client.token)

    def _ensure_client(self) -> HsrClient:
        """获取已登录客户端。

        Returns:
            已登录的 :class:`HsrClient`。

        Raises:
            ValueError: 尚未登录时抛出。
        """
        if self._client is None or not self._client.token:
            raise ValueError("请先登录")
        return self._client

    # ------------------------------------------------------------------ 登录
    def _action_login(self, params: dict[str, Any]) -> ApiResult:
        """使用表单账号密码登录。

        Args:
            params: 必须包含 ``username`` 与 ``password``。

        Returns:
            登录结果。
        """
        username: str = str(params.get("username") or "").strip()
        password: str = str(params.get("password") or "")
        if not username or not password:
            return failure("请在设置中填写学号/账号和密码")

        config: dict[str, Any] = load_config()
        timeout: float = float(
            config.get("network", {}).get("timeout_seconds", 40)
        )
        client: HsrClient = HsrClient(timeout=timeout)
        # 步骤 1：自动完成滑块验证码并登录。
        token: str = client.login(username, password)
        self._client = client
        self._records = []
        # 步骤 2：登录成功后持久化凭据；V2 密码保存到 hsr 分组。
        update_config({"username": username, "hsr": {"password": password}})
        return success({"username": username, "logged_in": bool(token)})

    def _action_login_saved(self, params: dict[str, Any]) -> ApiResult:
        """使用配置文件中已保存的凭据登录。

        Args:
            params: 未使用的动作参数。

        Returns:
            登录结果。
        """
        username, password = self._read_credentials()
        if not username or not password:
            return failure("尚未在设置中保存账号密码")
        return self._action_login({"username": username, "password": password})

    def _action_logout(self, params: dict[str, Any]) -> ApiResult:
        """退出登录并清空会话。

        Args:
            params: 未使用的动作参数。

        Returns:
            退出结果。
        """
        self._client = None
        self._records = []
        return success({"logged_in": False})

    # ------------------------------------------------------------------ 列表
    def _action_list_exams(self, params: dict[str, Any]) -> ApiResult:
        """读取并装饰考试列表。

        Args:
            params: 未使用的动作参数。

        Returns:
            含 ``records`` 的结果。
        """
        client: HsrClient = self._ensure_client()
        response: dict[str, Any] = client.exam_list()
        raw_records: Any = response.get("records") or response.get("rows") or []
        records: list[dict[str, Any]] = []
        if isinstance(raw_records, list):
            for raw_record in raw_records:
                if isinstance(raw_record, dict):
                    records.append(self._decorate_record(raw_record))
        self._records = records
        return success({"records": records})

    def _decorate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """为考试记录附加状态与剩余次数。

        Args:
            record: 服务端原始考试记录。

        Returns:
            新的考试记录字典。
        """
        decorated: dict[str, Any] = dict(record)
        status, remaining, available = self._evaluate_record(record)
        decorated["status"] = status
        decorated["remaining"] = remaining
        decorated["available"] = available
        return decorated

    def _evaluate_record(self, record: dict[str, Any]) -> tuple[str, int, bool]:
        """计算考试状态。

        Args:
            record: 服务端原始考试记录。

        Returns:
            ``(状态文本, 剩余次数, 是否可作答)``。
        """
        now: datetime = datetime.now()
        start: datetime | None = self._parse_time(record.get("examStartTime"))
        end: datetime | None = self._parse_time(record.get("examEndTime"))
        try:
            remaining: int = int(record.get("participateStrategy") or 0) - int(
                record.get("participateCount") or 0
            )
        except (TypeError, ValueError):
            remaining = 0
        if end and now > end:
            return "已截止", remaining, False
        if start and now < start:
            return "未开始", remaining, False
        if remaining <= 0:
            return "次数用完", remaining, False
        return "可作答（剩余 %d 次）" % remaining, remaining, True

    @staticmethod
    def _parse_time(value: object) -> datetime | None:
        """解析服务端时间字符串。

        Args:
            value: 原始时间值。

        Returns:
            解析成功返回 ``datetime``，否则 ``None``。
        """
        if not value:
            return None
        text: str = str(value)[:19]
        for date_format in _DATE_FORMATS:
            try:
                return datetime.strptime(text, date_format)
            except ValueError:
                continue
        return None

    # ------------------------------------------------------------------ 答题
    def _action_start_exam(self, params: dict[str, Any]) -> ApiResult:
        """开始考试、自动作答并提交。

        该动作会消耗一次作答机会，UI 必须先完成二次确认。

        Args:
            params: 必须包含 ``exam_id``。

        Returns:
            提交结果与命中统计。
        """
        try:
            exam_id: int = int(params.get("exam_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("考试 ID 无效") from exc

        record: dict[str, Any] | None = self._find_record(exam_id)
        if record is None:
            # 列表可能已过期，先刷新一次再查找。
            self._action_list_exams({})
            record = self._find_record(exam_id)
        if record is None:
            raise ValueError("未找到指定考试，请刷新列表")
        status, _remaining, available = self._evaluate_record(record)
        if not available:
            raise ValueError("该考试当前不可作答：%s" % status)

        client: HsrClient = self._ensure_client()
        # 步骤 1：考试预检。
        client.start_precheck(exam_id)
        # 步骤 2：生成个人试卷（消耗一次机会）。
        paper: dict[str, Any] = client.start_exam(exam_id)
        # 步骤 3：在本地题库中匹配答案。
        rows: list[dict[str, Any]] = self._build_answers(paper)
        missing: list[dict[str, Any]] = [
            {"index": row["index"], "content": row["content"]}
            for row in rows if not row["codes"]
        ]
        risky: list[dict[str, Any]] = [
            {"index": row["index"], "content": row["content"]}
            for row in rows if row.get("fallback")
        ]
        # 步骤 4：构造与原版一致的提交结构。
        payload: dict[str, Any] = self._build_commit_payload(paper, rows, exam_id)
        # 步骤 5：提交试卷。
        response: dict[str, Any] = client.commit_exam(payload)
        if response.get("code") != 200:
            return failure(
                "提交失败: %s" % (response.get("msg") or response.get("code")),
                {
                    "exam_name": paper.get("examName"),
                    "hit_count": len(rows) - len(missing),
                    "total": len(rows),
                    "missing": missing,
                    "risky": risky,
                },
            )

        score_data: Any = response.get("data")
        score: Any = (
            score_data.get("totalScore") if isinstance(score_data, dict) else score_data
        )
        summary: dict[str, Any] = {
            "exam_name": paper.get("examName"),
            "total": len(rows),
            "hit_count": len(rows) - len(missing),
            "missing": missing,
            "risky": risky,
            "score": score,
            "submitted": True,
            "exam_id": exam_id,
            "personal_exam_id": paper.get("id"),
            "duration": paper.get("duration"),
        }
        self._last_exam = summary
        return success(summary)

    def _find_record(self, exam_id: int) -> dict[str, Any] | None:
        """在缓存的考试列表中查找记录。

        Args:
            exam_id: 考试 ID。

        Returns:
            命中的记录；未找到返回 ``None``。
        """
        for record in self._records:
            try:
                if int(record.get("id")) == exam_id:
                    return record
            except (TypeError, ValueError):
                continue
        return None

    def _build_answers(self, paper: dict[str, Any]) -> list[dict[str, Any]]:
        """为试卷中的每道题匹配答案。

        Args:
            paper: 试卷数据。

        Returns:
            每道题的匹配结果行，顺序与 ``questionList`` 一致。
        """
        rows: list[dict[str, Any]] = []
        question_list: Any = paper.get("questionList") or []
        if not isinstance(question_list, list):
            question_list = []
        for index, raw_question in enumerate(question_list):
            question: dict[str, Any] = (
                raw_question if isinstance(raw_question, dict) else {}
            )
            options: list[dict[str, Any]] = []
            raw_options: Any = question.get("optionList") or []
            if isinstance(raw_options, list):
                options = [option for option in raw_options if isinstance(option, dict)]
            # 多选判定与原版一致：multiFlag 或 questionType 任一为 "1"。
            multi: bool = (
                str(question.get("multiFlag")) == "1"
                or str(question.get("questionType")) == "1"
            )
            content: str = str(question.get("content") or "")
            item, score, method = self._bank.lookup_item(content)
            trace: list[bool] = []
            if item is not None and item.get("answer_options"):
                codes: list[str] = self._bank.resolve_answer_options(
                    item["answer_options"], options, multi=multi, trace=trace
                )
            else:
                answer_text: str | None = item.get("a") if item is not None else None
                codes = self._bank.resolve_answer(answer_text, options, multi=multi)
            fallback: bool = bool(trace) and not all(trace)
            rows.append({
                "index": index + 1,
                "content": content,
                "multi": multi,
                "codes": codes,
                "method": method,
                "score": score,
                "fallback": fallback,
            })
        return rows

    def _build_commit_payload(
        self,
        paper: dict[str, Any],
        rows: list[dict[str, Any]],
        exam_id: int,
    ) -> dict[str, Any]:
        """构造与原版兼容的提交 payload。

        Args:
            paper: 试卷数据。
            rows: :meth:`_build_answers` 的结果。
            exam_id: 考试 ID。

        Returns:
            可直接提交给 ``/exam/commit`` 的字典。
        """
        question_list: Any = paper.get("questionList") or []
        payload: dict[str, Any] = {
            "hasSubmitted": False,
            "questionList": question_list,
            "answerList": [],
            "examName": paper.get("examName"),
            "duration": paper.get("duration"),
            "examCode": paper.get("examCode"),
            "examDesc": paper.get("examDesc"),
            "candidateCode": paper.get("candidateCode"),
            "examId": exam_id,
            "examPaperId": paper.get("examPaperId"),
            "personalExamId": paper.get("id"),
        }
        base_answers: Any = paper.get("answerList") or []
        if not isinstance(base_answers, list):
            base_answers = []
        answer_list: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            item: dict[str, Any] = (
                dict(base_answers[index])
                if index < len(base_answers) and isinstance(base_answers[index], dict)
                else {}
            )
            codes: list[str] = list(row.get("codes") or [])
            if row.get("multi"):
                item["optionCode"] = ",".join(codes)
            else:
                item["optionCode"] = codes[0] if codes else ""
            item["optionsCodeList"] = None
            answer_list.append(item)
        payload["answerList"] = answer_list
        return payload

    # ------------------------------------------------------------------ 题库
    def _action_get_bank_info(self, params: dict[str, Any]) -> ApiResult:
        """返回内置题库概况。

        Args:
            params: 未使用的动作参数。

        Returns:
            题库题量、章节、版本等信息。
        """
        versions: list[str] = runtime_data.list_versions(_BANK_FEATURE_KEY)
        latest: str = runtime_data.latest_version(_BANK_FEATURE_KEY)
        chapters: list[str] = []
        for item in self._bank.items:
            chapter = str(item.get("chapter") or "")
            if chapter and chapter not in chapters:
                chapters.append(chapter)
        return success({
            "feature": _BANK_FEATURE_KEY,
            "versions": versions,
            "latest_version": latest,
            "count": self._bank.count,
            "chapters": chapters,
        })
