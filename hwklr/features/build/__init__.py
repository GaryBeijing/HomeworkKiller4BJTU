# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-01 12:40
# 文件名: __init__.py
# 主要用途: 实现“构建”功能：导出参数状态、设置板块（输出目录/开发格式/Feature 开发标记）与后台构建任务。
# 文件版本: 2.1.0
"""构建功能。

- 页面只负责收集“导出显示版本号”和“是否开发构建”，并轮询构建日志；
- 构建的实际工作交给 :mod:`hwklr.features.build.packager`；
- 设置板块注册“默认构建目录”“开发构建格式”“Feature 开发标记”。
"""
from __future__ import annotations

import logging
import sys
import threading
import traceback
import uuid
from typing import Any, Final

from hwklr import __version__ as APP_VERSION
from hwklr.config import load_config
from hwklr.features.base import ApiResult, Feature, failure, success
from hwklr.features.manifest import OFFICIAL_FEATURES, FeatureSpec, feature_version
from hwklr.features.settings import FeatureSettingsGroup, SettingsFieldSpec

from .packager import (
    VERSION_PATTERN,
    BuildError,
    build_package,
    python_embed_url,
    python_embed_version,
    pyinstaller_version,
    resolve_output_dir,
)

__version__ = "2.1.0"
__author__ = "Gary"
__all__ = ["BuildFeature"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_MAX_LOG_LINES: Final[int] = 2000
_DEV_FORMAT_OPTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("executable", "executable（可执行文件）"),
    ("zip", "zip（python-embed 运行时）"),
)


def _is_dev_state(value: Any) -> bool:
    """判断配置中的开发标记。

    Args:
        value: 配置值。

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
    return str(value).strip().lower() in {"1", "true", "yes", "on", "是"}


class BuildFeature(Feature):
    """“构建”标签页功能。"""

    def __init__(self, universal_param: dict[str, Any]) -> None:
        """初始化构建功能。

        Args:
            universal_param: 窗口层注入的通用参数。
        """
        super().__init__(universal_param)
        self._job_lock: threading.Lock = threading.Lock()
        self._job: dict[str, Any] = self._idle_job()
        self._thread: threading.Thread | None = None
        self._settings_group: FeatureSettingsGroup = self._build_settings_group()

    # ------------------------------------------------------------------ 设置
    @property
    def settings_group(self) -> FeatureSettingsGroup:
        """返回构建设置板块。

        Returns:
            含输出目录、开发格式与 Feature 开发标记的设置组。
        """
        return self._settings_group

    def _official_rows(self) -> list[dict[str, Any]]:
        """返回官方功能及其版本。

        Returns:
            形如 ``[{"name": ..., "version": ..., "dev": ...}]`` 的列表。
        """
        config: dict[str, Any] = load_config()
        setting: dict[str, Any] = (
            config.get("build") if isinstance(config.get("build"), dict) else {}
        )
        stored: Any = setting.get("features")
        states: dict[str, Any] = dict(stored) if isinstance(stored, dict) else {}
        rows: list[dict[str, Any]] = []
        for spec in OFFICIAL_FEATURES:
            rows.append({
                "name": spec.name,
                "version": feature_version(spec),
                "dev": _is_dev_state(states.get(spec.name, "release")),
            })
        return rows

    def _build_settings_group(self) -> FeatureSettingsGroup:
        """构建“构建”设置板块。

        Returns:
            构建设置组。
        """

        def values_getter() -> dict[str, Any]:
            """读取构建配置。"""
            config: dict[str, Any] = load_config()
            setting: dict[str, Any] = (
                config.get("build") if isinstance(config.get("build"), dict) else {}
            )
            stored: Any = setting.get("features")
            states: dict[str, Any] = dict(stored) if isinstance(stored, dict) else {}
            features: dict[str, str] = {
                spec.name: (
                    "dev"
                    if _is_dev_state(states.get(spec.name, "release"))
                    else "release"
                )
                for spec in OFFICIAL_FEATURES
            }
            return {
                "output_dir": str(setting.get("output_dir") or ""),
                "dev_format": str(setting.get("dev_format") or "executable"),
                "features": features,
            }

        def exporter(values: dict[str, Any]) -> dict[str, Any]:
            """导出构建配置。"""
            raw_features: Any = values.get("features")
            feature_map: dict[str, str] = {}
            if isinstance(raw_features, dict):
                for name, state in raw_features.items():
                    feature_map[str(name)] = (
                        "dev" if _is_dev_state(state) else "release"
                    )
            return {
                "build": {
                    "output_dir": str(values.get("output_dir") or ""),
                    "dev_format": str(values.get("dev_format") or "executable"),
                    "features": feature_map,
                }
            }

        rows: list[dict[str, Any]] = self._official_rows()
        return FeatureSettingsGroup(
            group_id="build",
            title="构建",
            description=(
                "导出分发包的默认目录与格式。标记为“开发构建”的功能在发布构建中"
                "不会被打包，适合仍在开发或含调试内容的功能。"
            ),
            field_specs=(
                SettingsFieldSpec(
                    key="output_dir",
                    label="默认构建目录",
                    kind="text",
                    placeholder="/build/",
                    is_necessary=False,
                    help="选填；留空使用项目根目录 /build/，相对路径以项目根目录为基准。",
                ),
                SettingsFieldSpec(
                    key="dev_format",
                    label="开发构建格式",
                    kind="select",
                    options=_DEV_FORMAT_OPTIONS,
                    help="仅在构建页勾选“开发构建”时生效。",
                ),
                SettingsFieldSpec(
                    key="features",
                    label="Feature 开发标记",
                    kind="features",
                    options=tuple(
                        (row["name"], row["version"]) for row in rows
                    ),
                    alert=True,
                    help="勾选后该功能在 config.json 中标记为 dev，发布构建将跳过该功能。",
                ),
            ),
            values_getter=values_getter,
            exporter=exporter,
            complete_checker=lambda: True,
            missing_getter=lambda: [],
        )

    # ------------------------------------------------------------------ 分发
    def handle(self, action: str, params: dict[str, Any]) -> ApiResult:
        """分发构建动作。

        Args:
            action: 动作名称。
            params: 动作参数。

        Returns:
            统一格式的结果字典。
        """
        try:
            if action == "get_state":
                return success(self._state_payload())
            if action == "start_build":
                return self._start_build(params)
            if action == "get_job":
                return self._get_job(params)
            return failure("未知动作: %s" % action)
        except Exception as exc:  # 兜底，保证错误回传到 UI。
            _LOGGER.exception("构建功能未预期异常")
            return failure("操作失败: %s" % exc)

    def _state_payload(self) -> dict[str, Any]:
        """生成构建页所需的静态状态。

        Returns:
            工具版本、配置摘要、功能列表与任务快照。
        """
        config: dict[str, Any] = load_config()
        setting: dict[str, Any] = (
            config.get("build") if isinstance(config.get("build"), dict) else {}
        )
        output_value: str = str(setting.get("output_dir") or "")
        pyinstaller: str = pyinstaller_version()
        return {
            "version": APP_VERSION,
            "buildable": not bool(getattr(sys, "frozen", False)),
            "output_dir": output_value,
            "output_path": str(resolve_output_dir(output_value)),
            "dev_format": str(setting.get("dev_format") or "executable"),
            "features": self._official_rows(),
            "tool": {
                "builder": __version__,
                "pyinstaller": pyinstaller,
                "available": bool(pyinstaller),
                "python": "%d.%d.%d" % (
                    sys.version_info.major,
                    sys.version_info.minor,
                    sys.version_info.micro,
                ),
                "embed": python_embed_version(),
                "embed_url": python_embed_url(),
            },
            "job": self._job_snapshot(),
        }

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
            "progress": 0,
            "log": [],
            "result": None,
            "error": "",
        }

    def _job_snapshot(self) -> dict[str, Any]:
        """返回任务状态的线程安全副本。

        Returns:
            任务状态字典。
        """
        with self._job_lock:
            job: dict[str, Any] = dict(self._job)
            job["log"] = list(self._job.get("log", []))
            result: Any = self._job.get("result")
            job["result"] = dict(result) if isinstance(result, dict) else result
            return job

    def _append_log(self, message: str) -> None:
        """向任务日志追加一行。

        Args:
            message: 日志文本。
        """
        from datetime import datetime

        line: str = "[%s] %s" % (datetime.now().strftime("%H:%M:%S"), message)
        with self._job_lock:
            lines: list[str] = self._job.setdefault("log", [])
            lines.append(line)
            if len(lines) > _MAX_LOG_LINES:
                del lines[: len(lines) - _MAX_LOG_LINES]

    def _set_phase(self, phase: str, message: str, progress: int) -> None:
        """更新任务阶段、说明与进度。

        Args:
            phase: 阶段标识。
            message: 面向用户的说明。
            progress: 0~100 的进度。
        """
        with self._job_lock:
            self._job["phase"] = phase
            self._job["message"] = message
            self._job["progress"] = max(0, min(100, int(progress)))

    def _start_build(self, params: dict[str, Any]) -> ApiResult:
        """启动一次后台构建。

        Args:
            params: 必须包含 ``version``，可选 ``dev_build``。

        Returns:
            新任务的 ``job_id``。
        """
        if getattr(sys, "frozen", False):
            return failure("已打包的应用不能再次构建，请从源码运行本程序")
        version: str = str(params.get("version") or APP_VERSION).strip()
        if not VERSION_PATTERN.match(version):
            return failure("版本号不合法！请填写 x.x.x 形式（例如 2.1.0）")
        dev_build: bool = _as_bool(params.get("dev_build"))
        with self._job_lock:
            if self._job.get("running"):
                return failure("已有构建任务正在运行，请等待完成")
            job_id: str = uuid.uuid4().hex[:12]
            self._job = {
                "job_id": job_id,
                "running": True,
                "done": False,
                "phase": "starting",
                "message": "准备构建…",
                "progress": 0,
                "log": [],
                "result": None,
                "error": "",
            }
        config: dict[str, Any] = load_config()
        setting: dict[str, Any] = (
            config.get("build") if isinstance(config.get("build"), dict) else {}
        )
        stored: Any = setting.get("features")
        states: dict[str, Any] = dict(stored) if isinstance(stored, dict) else {}
        dev_features: set[str] = {
            spec.name
            for spec in OFFICIAL_FEATURES
            if _is_dev_state(states.get(spec.name, "release"))
        }
        output_dir: str = str(setting.get("output_dir") or "")
        dev_format: str = str(setting.get("dev_format") or "executable")
        self._thread = threading.Thread(
            target=self._run_job,
            args=(job_id, version, dev_build, output_dir, dev_format, dev_features),
            name="BuildJob-%s" % job_id,
            daemon=True,
        )
        self._thread.start()
        return success({"job_id": job_id})

    def _run_job(
        self,
        job_id: str,
        version: str,
        dev_build: bool,
        output_dir: str,
        dev_format: str,
        dev_features: set[str],
    ) -> None:
        """后台线程：执行构建并写入任务状态。

        Args:
            job_id: 任务 ID。
            version: 导出显示版本号。
            dev_build: 是否开发构建。
            output_dir: 输出目录配置。
            dev_format: 开发构建格式。
            dev_features: 标记为 dev 的功能名称。
        """
        try:
            self._append_log("开始构建任务 %s" % job_id)
            result: dict[str, Any] = build_package(
                version=version,
                dev_build=dev_build,
                output_dir=output_dir,
                dev_format=dev_format,
                dev_features=dev_features,
                log=self._append_log,
                set_phase=self._set_phase,
            )
            with self._job_lock:
                self._job.update({
                    "running": False,
                    "done": True,
                    "phase": "done",
                    "message": "构建完成",
                    "progress": 100,
                    "result": result,
                })
            self._append_log("产物路径：%s" % result.get("path"))
        except BuildError as exc:
            self._append_log("构建失败：%s" % exc)
            with self._job_lock:
                self._job.update({
                    "running": False,
                    "done": True,
                    "phase": "error",
                    "message": "构建失败",
                    "error": str(exc),
                })
        except Exception as exc:  # 记录完整堆栈，便于排查。
            _LOGGER.exception("构建任务异常")
            self._append_log(traceback.format_exc())
            with self._job_lock:
                self._job.update({
                    "running": False,
                    "done": True,
                    "phase": "error",
                    "message": "构建失败",
                    "error": "构建异常: %s" % exc,
                })

    def _get_job(self, params: dict[str, Any]) -> ApiResult:
        """返回当前构建任务状态。

        Args:
            params: 可选 ``job_id``；不匹配当前任务时返回失败。

        Returns:
            任务状态。
        """
        snapshot: dict[str, Any] = self._job_snapshot()
        requested: str = str(params.get("job_id") or "")
        if requested and snapshot.get("job_id") != requested:
            return failure("构建任务不存在或已过期")
        return success(snapshot)
