# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-01 12:40
# 最后更新: 2026-11-09 19:05
# 文件名: __init__.py
# 主要用途: 实现“构建”功能：程序构建/插件构建切换、插件工程管理、开发环境迁移、导出参数与后台构建任务。
# 文件版本: 4.3.0
"""构建功能。

- 页面收集“导出显示版本号”“程序名称”“程序图标”和“是否开发构建”；
- 构建的实际工作交给 :mod:`hwklr.features.build.packager`；
- 设置板块注册“默认构建目录”“开发构建格式”“Feature 开发标记”；
- 开发构建包启动后提供 HwklrVenv 开发环境搭建入口。
"""
from __future__ import annotations

import logging
import shutil
import sys
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from hwklr import APP_NAME, DEV_BUILD, __version__ as APP_VERSION
from hwklr.config import load_config, update_config
from hwklr.features.about import AboutMetadataGroup
from hwklr.features.base import ApiResult, Feature, failure, success
from hwklr.features.extensions import is_feature_enabled, set_feature_enabled
from hwklr.features.manifest import OFFICIAL_FEATURES, FeatureSpec, feature_version
from hwklr.features.settings import FeatureSettingsGroup, SettingsFieldSpec

from .devenv import (
    create_dev_venv,
    dev_env_ready,
    find_system_python,
    source_path,
    venv_path,
)
from .packager import (
    VERSION_PATTERN,
    BuildError,
    build_package,
    python_embed_url,
    python_embed_version,
    pyinstaller_version,
    resolve_output_dir,
)

__version__ = "4.3.0"
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


def _default_export_version() -> str:
    """计算构建页默认导出版本号。

    规则为“原三段版本号 + 12 位时间戳对 9973 取模”的第四段，
    例如当前 2.1.3、构建时间 261101125959 → 2.1.3.7559。

    Returns:
        形如 ``x.y.z.w`` 的版本号。
    """
    base_parts: list[str] = str(APP_VERSION).split(".")[:3]
    if len(base_parts) < 3:
        return str(APP_VERSION)
    stamp: str = datetime.now().strftime("%y%m%d%H%M%S")
    return "%s.%d" % (".".join(base_parts), int(stamp) % 9973)


class BuildFeature(Feature):
    """“构建”标签页功能。"""

    def __init__(self, universal_param: dict[str, Any]) -> None:
        """初始化构建功能。

        Args:
            universal_param: 窗口层注入的通用参数。
        """
        super().__init__(universal_param)
        self._job_lock: threading.Lock = threading.Lock()
        self._dev_lock: threading.Lock = threading.Lock()
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

    @property
    def about_meta(self) -> AboutMetadataGroup:
        """返回构建功能在“关于”页的元信息。

        Returns:
            插件名、包名、作者与版本。
        """
        return AboutMetadataGroup(
            name="构建",
            package="BUILD",
            author="Gary",
            version=__version__,
            update_date="2026-11-03",
            official=True,
            feature_key="构建",
            description="将当前程序导出为可直接运行的目录、zip 或可执行文件，并构建插件发布包。",
        )

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
                "plugin_template": str(setting.get("plugin_template") or ""),
                "plugin_project": str(setting.get("plugin_project") or ""),
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
                    "plugin_template": str(
                        values.get("plugin_template") or ""
                    ).strip(),
                    "plugin_project": str(
                        values.get("plugin_project") or ""
                    ).strip(),
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
                    key="plugin_template",
                    label="选择插件工程模板",
                    kind="file",
                    placeholder="留空使用随程序分发的模板",
                    is_necessary=False,
                    help=(
                        "选择“新建插件工程”时使用的 zip 模板；留空时使用 "
                        "hwklr/features/build/vendor/plugin-template.zip。"
                    ),
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
            enabled_getter=lambda: is_feature_enabled("构建"),
            enabled_setter=lambda enabled: set_feature_enabled("构建", enabled),
            enabled_editable=True,
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
            if action == "setup_dev_venv":
                return self._setup_dev_venv(params)
            if action == "choose_plugin_project":
                return self._choose_plugin_project(params)
            if action == "create_plugin_project":
                return self._create_plugin_project(params)
            if action == "test_plugin":
                return self._test_plugin(params)
            if action == "start_plugin_build":
                return self._start_plugin_build(params)
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
        python_found: tuple[list[str], str] | None = (
            find_system_python() if DEV_BUILD else None
        )
        return {
            "version": APP_VERSION,
            "default_version": _default_export_version(),
            "default_name": APP_NAME,
            # 开发构建产物中只允许构建插件，程序构建被屏蔽。
            "buildable": (
                not bool(getattr(sys, "frozen", False)) and not bool(DEV_BUILD)
            ),
            "dev_build": bool(DEV_BUILD),
            "dev_env_ready": dev_env_ready(),
            "dev_env_path": str(venv_path()),
            "dev_source_path": str(source_path()),
            "python_available": python_found is not None,
            "python_path": python_found[1] if python_found else "",
            "output_dir": output_value,
            "output_path": str(resolve_output_dir(output_value)),
            "dev_format": str(setting.get("dev_format") or "executable"),
            "modes": {
                "program": (
                    not bool(getattr(sys, "frozen", False)) and not bool(DEV_BUILD)
                ),
                "plugin": True,
            },
            "default_mode": "plugin" if DEV_BUILD else "program",
            "plugin": self._plugin_state(setting),
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

    def _plugin_state(self, setting: dict[str, Any]) -> dict[str, Any]:
        """生成插件构建面板状态。

        Args:
            setting: config.json 的 build 分组。

        Returns:
            插件工程、模板、Git 与开发环境状态。
        """
        from pathlib import Path

        from hwklr.features.extensions import (
            ExtensionError,
            bundled_template_zip,
            project_extension_root,
            read_project_metadata,
        )

        configured_template: str = str(setting.get("plugin_template") or "").strip()
        template: Path | None = (
            Path(configured_template).expanduser()
            if configured_template
            else bundled_template_zip()
        )
        project: str = str(setting.get("plugin_project") or "").strip()
        project_valid: bool = False
        project_name: str = ""
        project_error: str = ""
        if project:
            try:
                metadata: dict[str, Any] = read_project_metadata(Path(project))
                project_valid = True
                project_name = str(metadata.get("name") or "")
            except ExtensionError as exc:
                project_error = str(exc)
        venv_python: Path = venv_path() / "Scripts" / "python.exe"
        return {
            "project": project,
            "project_valid": project_valid,
            "project_name": project_name,
            "project_error": project_error,
            "template": str(template) if template is not None else "",
            "template_available": bool(
                template is not None and template.is_file()
            ),
            "git_available": bool(shutil.which("git")),
            "venv_ready": venv_python.is_file(),
            "extension_root": str(project_extension_root()),
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
            params: 必须包含 ``version``，可选 ``dev_build``、
                ``program_name``、``icon_data``、``icon_filename``。

        Returns:
            新任务的 ``job_id``。
        """
        if getattr(sys, "frozen", False):
            return failure("已打包的应用不能再次构建，请从源码运行本程序")
        if DEV_BUILD:
            return failure("开发构建产物中仅支持构建插件")
        version: str = str(
            params.get("version") or _default_export_version()
        ).strip()
        if not VERSION_PATTERN.match(version):
            return failure(
                "版本号不合法！请填写 x.x.x 或 x.x.x.x 形式（例如 2.1.3.7559）"
            )
        dev_build: bool = _as_bool(params.get("dev_build"))
        program_name: str = str(params.get("program_name") or "").strip()
        icon_data: str = str(params.get("icon_data") or "")
        icon_filename: str = str(params.get("icon_filename") or "")
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
            args=(
                job_id,
                version,
                dev_build,
                output_dir,
                dev_format,
                dev_features,
                program_name,
                icon_data,
                icon_filename,
            ),
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
        program_name: str,
        icon_data: str,
        icon_filename: str,
    ) -> None:
        """后台线程：执行构建并写入任务状态。

        Args:
            job_id: 任务 ID。
            version: 导出显示版本号。
            dev_build: 是否开发构建。
            output_dir: 输出目录配置。
            dev_format: 开发构建格式。
            dev_features: 标记为 dev 的功能名称。
            program_name: 程序显示名称。
            icon_data: 图标 Base64/Data URL。
            icon_filename: 图标原始文件名。
        """
        try:
            self._append_log("开始构建任务 %s" % job_id)
            result: dict[str, Any] = build_package(
                version=version,
                dev_build=dev_build,
                output_dir=output_dir,
                dev_format=dev_format,
                dev_features=dev_features,
                program_name=program_name,
                icon_data=icon_data,
                icon_filename=icon_filename,
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

    # ------------------------------------------------------------------ 插件
    def _dialogs(self) -> dict[str, Any]:
        """返回窗口层注入的对话框回调。

        Returns:
            回调字典。
        """
        value: Any = self._universal_param.get("dialogs")
        return value if isinstance(value, dict) else {}

    def _extension_callbacks(self) -> dict[str, Any]:
        """返回窗口层注入的扩展回调。

        Returns:
            回调字典。
        """
        value: Any = self._universal_param.get("extensions")
        return value if isinstance(value, dict) else {}

    def _save_plugin_project(self, path: str) -> None:
        """记住最近选择的插件工程。

        Args:
            path: 工程目录。
        """
        update_config({"build": {"plugin_project": str(path or "")}})

    def _current_plugin_project(self, params: dict[str, Any] | None = None) -> str:
        """读取本次动作或配置中的插件工程路径。

        Args:
            params: 动作参数；可覆盖配置。

        Returns:
            工程目录字符串。
        """
        value: str = str((params or {}).get("project") or "").strip()
        if value:
            return value
        config: dict[str, Any] = load_config()
        setting: dict[str, Any] = (
            config.get("build") if isinstance(config.get("build"), dict) else {}
        )
        return str(setting.get("plugin_project") or "").strip()

    def _choose_plugin_project(self, params: dict[str, Any]) -> ApiResult:
        """弹出目录选择框选择插件工程。

        Args:
            params: 未使用的动作参数。

        Returns:
            选择结果与工程元信息。
        """
        picker: Any = self._dialogs().get("pick_directory")
        if not callable(picker):
            return failure("当前环境不支持目录选择")
        from hwklr.features.extensions import (
            ExtensionError,
            project_extension_root,
            read_project_metadata,
        )

        initial: str = str(project_extension_root())
        try:
            path: Any = picker("选择插件工程", initial)
        except TypeError:
            path = picker("选择插件工程")
        except Exception as exc:
            return failure("打开目录选择框失败：%s" % exc)
        selected: str = str(path or "").strip()
        if not selected:
            return success({"path": "", "cancelled": True})
        try:
            metadata: dict[str, Any] = read_project_metadata(Path(selected))
        except ExtensionError as exc:
            return failure("所选目录不是有效的插件工程：%s" % exc)
        self._save_plugin_project(selected)
        return success({
            "path": selected,
            "name": str(metadata.get("name") or ""),
            "package": str(metadata.get("package") or ""),
            "cancelled": False,
        })

    def _create_plugin_project(self, params: dict[str, Any]) -> ApiResult:
        """从模板新建插件工程。

        Args:
            params: 必须包含 ``name``，可选 ``package``。

        Returns:
            新建工程路径与元信息。
        """
        from hwklr.features.extensions import (
            ExtensionError,
            create_plugin_project,
            read_project_metadata,
        )

        name: str = str(params.get("name") or "").strip()
        package: str = str(params.get("package") or "").strip()
        config: dict[str, Any] = load_config()
        setting: dict[str, Any] = (
            config.get("build") if isinstance(config.get("build"), dict) else {}
        )
        template: str = str(setting.get("plugin_template") or "").strip()
        try:
            target: Path = create_plugin_project(
                name,
                package,
                template_zip=template or None,
            )
            metadata: dict[str, Any] = read_project_metadata(target)
        except ExtensionError as exc:
            return failure(str(exc))
        self._save_plugin_project(str(target))
        return success({
            "path": str(target),
            "name": str(metadata.get("name") or name),
            "package": str(metadata.get("package") or package),
        })

    def _test_plugin(self, params: dict[str, Any]) -> ApiResult:
        """从工程目录临时加载插件（不写入配置，不随下次启动加载）。

        Args:
            params: 可选 ``project`` 覆盖当前工程。

        Returns:
            加载后的标签名与扩展信息。
        """
        from hwklr.features.extensions import ExtensionError, load_extension_dir

        project: str = self._current_plugin_project(params)
        if not project:
            return failure("请先选择插件工程")
        callback: Any = self._extension_callbacks().get("register_dir")
        if not callable(callback):
            return failure("当前环境不支持测试插件")
        try:
            info = load_extension_dir(Path(project))
            result: Any = callback(str(info.path), True)
        except Exception as exc:
            return failure(str(exc))
        payload: dict[str, Any] = (
            result if isinstance(result, dict) else {}
        )
        return success({
            "tab": str(payload.get("tab") or info.tab_name),
            "extension": info.payload(True),
        })

    def _start_plugin_build(self, params: dict[str, Any]) -> ApiResult:
        """在后台线程构建插件发布包。

        Args:
            params: 可选 ``project``。

        Returns:
            新任务的 ``job_id``。
        """
        from hwklr.features.extensions import ExtensionError, read_project_metadata

        project: str = self._current_plugin_project(params)
        if not project:
            return failure("请先选择插件工程")
        try:
            read_project_metadata(Path(project))
        except ExtensionError as exc:
            return failure("插件工程不合法：%s" % exc)
        with self._job_lock:
            if self._job.get("running"):
                return failure("已有构建任务正在运行，请等待完成")
            job_id: str = uuid.uuid4().hex[:12]
            self._job = {
                "job_id": job_id,
                "running": True,
                "done": False,
                "phase": "starting",
                "message": "准备构建插件…",
                "progress": 0,
                "log": [],
                "result": None,
                "error": "",
            }
        config: dict[str, Any] = load_config()
        setting: dict[str, Any] = (
            config.get("build") if isinstance(config.get("build"), dict) else {}
        )
        output_dir: str = str(setting.get("output_dir") or "")
        self._thread = threading.Thread(
            target=self._run_plugin_job,
            args=(job_id, project, output_dir),
            name="PluginBuildJob-%s" % job_id,
            daemon=True,
        )
        self._thread.start()
        return success({"job_id": job_id})

    def _run_plugin_job(
        self,
        job_id: str,
        project: str,
        output_dir: str,
    ) -> None:
        """后台线程：构建插件发布包并写入任务状态。

        Args:
            job_id: 任务 ID。
            project: 插件工程目录。
            output_dir: 输出目录配置。
        """
        try:
            from hwklr.features.extensions import build_plugin_package

            self._append_log("开始插件构建任务 %s" % job_id)
            result: dict[str, Any] = build_plugin_package(
                project,
                output_dir=output_dir,
                log=self._append_log,
                set_phase=self._set_phase,
            )
            with self._job_lock:
                self._job.update({
                    "running": False,
                    "done": True,
                    "phase": "done",
                    "message": "插件构建完成",
                    "progress": 100,
                    "result": result,
                })
            self._append_log("插件发布包：%s" % result.get("path"))
        except Exception as exc:  # 记录完整堆栈，便于排查。
            _LOGGER.exception("插件构建任务异常")
            self._append_log(traceback.format_exc())
            with self._job_lock:
                self._job.update({
                    "running": False,
                    "done": True,
                    "phase": "error",
                    "message": "插件构建失败",
                    "error": "插件构建失败: %s" % exc,
                })

    def _setup_dev_venv(self, params: dict[str, Any]) -> ApiResult:
        """在开发构建包中创建 HwklrVenv。

        Args:
            params: 未使用的动作参数。

        Returns:
            搭建结果；失败时返回可读原因。
        """
        if not DEV_BUILD:
            return failure("仅开发构建版本可搭建开发环境")
        if not self._dev_lock.acquire(blocking=False):
            return failure("正在搭建开发环境，请稍候")
        try:
            return success(create_dev_venv(log=self._append_log))
        except RuntimeError as exc:
            return failure(str(exc))
        finally:
            self._dev_lock.release()

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
