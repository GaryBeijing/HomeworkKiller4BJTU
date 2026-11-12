# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-10 10:30
# 最后更新: 2026-11-12 13:40
# 文件名: feature_specs.py
# 主要用途: 官方功能的单一元数据来源：显示名/稳定 id、配置默认值、关于信息、资源、数据库与打包声明。
# 文件版本: 4.6.1
"""官方功能元数据 registry。

本模块只依赖标准库，放在 ``hwklr`` 根包而不是 ``hwklr.features`` 下，
避免 ``config → features.__init__ → settings → config`` 的导入环。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

__version__ = "4.6.1"
__author__ = "Gary"
__all__ = [
    "FEATURE_BY_ID",
    "FEATURE_BY_NAME",
    "FeatureAssetSpec",
    "FeatureConfigSpec",
    "FeatureDbSpec",
    "FeatureMetaSpec",
    "FeaturePackagingSpec",
    "FeatureSpec",
    "OFFICIAL_FEATURES",
    "build_features_default",
    "feature_config_defaults",
    "feature_order",
    "feature_provider_specs",
    "official_sections",
]


@dataclass(frozen=True)
class FeatureConfigSpec:
    """一个功能在 config.json 中的板块。"""

    section: str
    defaults: tuple[tuple[str, Any], ...] = ()
    legacy_sections: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeatureMetaSpec:
    """关于页使用的功能元信息。"""

    package: str
    author: str
    update_date: str
    official: bool = True
    description: str = ""


@dataclass(frozen=True)
class FeatureDbSpec:
    """功能的数据库 provider、源文件和裁剪信息。"""

    base_name: str
    provider_module: str
    provider_class: str
    source_files: tuple[str, ...] = ()
    provider_modules: tuple[str, ...] = ()
    runtime_asset_prefixes: tuple[str, ...] = ()
    excluded_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeatureAssetSpec:
    """前端资源相对路径；为空时由 view_data 约定推导。"""

    html: str = ""
    css: tuple[str, ...] = ()
    js: tuple[str, ...] = ()
    runtime_dirs: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeaturePackagingSpec:
    """PyInstaller 打包声明。"""

    hidden_imports: tuple[str, ...] = ()
    collect_submodules: tuple[str, ...] = ()
    collect_all: tuple[str, ...] = ()
    extra_modules: tuple[str, ...] = ()
    extra_excludes: tuple[str, ...] = ()
    dev_default: str = "release"
    always_dev: bool = False
    plugin_template: str = ""


@dataclass(frozen=True)
class FeatureSpec:
    """一个官方功能的完整静态描述。

    前五个字段保持与原 ``FeatureSpec`` 的位置兼容；新增字段都有默认值。
    """

    name: str
    module: str
    class_name: str
    view_dir: str
    description: str
    id: str = ""
    order: int = 0
    aliases: tuple[str, ...] = ()
    config: FeatureConfigSpec | None = None
    meta: FeatureMetaSpec | None = None
    db: FeatureDbSpec | None = None
    assets: FeatureAssetSpec | None = None
    packaging: FeaturePackagingSpec = field(default_factory=FeaturePackagingSpec)

    @property
    def stable_id(self) -> str:
        """返回稳定 id；未显式声明时使用模块包名。"""
        return self.id or self.module.rsplit(".", 1)[-1]


OFFICIAL_FEATURES: Final[tuple[FeatureSpec, ...]] = (
    FeatureSpec(
        name="高铁纵横",
        module="hwklr.features.hsr",
        class_name="HSRFeature",
        view_dir="hsr",
        description="登录高铁答题系统，按题库自动匹配答案并提交考试。",
        id="hsr",
        order=10,
        config=FeatureConfigSpec(
            section="hsr",
            defaults=(("password", ""), ("enabled", True)),
        ),
        meta=FeatureMetaSpec(
            package="HSR",
            author="PhiloK (Gary remastered)",
            update_date="2026-11-08",
            description="登录高铁答题系统，按题库自动匹配答案并提交考试。",
        ),
        db=FeatureDbSpec(
            base_name="hsr",
            provider_module="hwklr.db.hsrdb",
            provider_class="HSRDb",
            source_files=("hwklr/db/hsr_sources.json",),
            provider_modules=("hwklr.db.hsrdb",),
            runtime_asset_prefixes=("hwklr/runtime_data/hsr_bank_",),
            excluded_paths=("hwklr/db/hsrdb.py", "hwklr/db/hsr_sources.json"),
        ),
    ),
    FeatureSpec(
        name="C程序设计",
        module="hwklr.features.cprog",
        class_name="CProgrammingFeature",
        view_dir="cprog",
        description="CITEL 课程题目辅助：启发模式逐步讲解，题解模式生成并提交参考实现。",
        id="cprog",
        order=20,
        config=FeatureConfigSpec(
            section="c_programming",
            defaults=(
                ("provider", "deepseek"),
                ("model", "deepseek-flash"),
                ("base_url", "https://api.deepseek.com"),
                ("api_key", ""),
                ("thinking_level", "auto"),
                ("max_concurrency", 8),
                ("enable_solution_mode", True),
                ("last_course_id", None),
                ("enabled", True),
            ),
        ),
        meta=FeatureMetaSpec(
            package="CPROG",
            author="Gary",
            update_date="2026-11-03",
            description="CITEL 课程题目辅助：启发模式逐步讲解，题解模式生成并提交参考实现。",
        ),
    ),
    FeatureSpec(
        name="中国大学慕课",
        module="hwklr.features.icourse",
        class_name="IcourseFeature",
        view_dir="icourse",
        description="登录中国大学慕课，批量完成课程视频、文档、测验与讨论任务。",
        id="icourse",
        order=30,
        config=FeatureConfigSpec(
            section="icourse",
            defaults=(
                ("account", ""),
                ("password", ""),
                ("account_type", "icourse"),
                ("workers", 8),
                ("video_rate", 2.0),
                ("submit_quizzes", False),
                ("publish_discussions", False),
                ("answer_ttl_hours", 24),
                ("auto_sync_answers", True),
                ("download_documents", True),
                ("retain_data", True),
                ("enabled", True),
            ),
        ),
        meta=FeatureMetaSpec(
            package="ICourse",
            author="Gary",
            update_date="2026-11-09",
            description="登录中国大学慕课，批量完成课程视频、文档、测验与讨论任务。",
        ),
        assets=FeatureAssetSpec(
            html="icourse/index.html",
            css=("icourse/css/icourse.css",),
            js=(
                "icourse/js/core.js",
                "icourse/js/login.js",
                "icourse/js/courses.js",
                "icourse/js/tasks.js",
                "icourse/js/sync.js",
                "icourse/js/job.js",
                "icourse/js/notices.js",
                "icourse/js/icourse.js",
            ),
        ),
        db=FeatureDbSpec(
            base_name="icourse",
            provider_module="hwklr.db.icoursedb",
            provider_class="IcourseDb",
            source_files=("hwklr/db/icourse_sources.json",),
            provider_modules=(
                "hwklr.db.icoursedb",
                "hwklr.db.icourse_models",
                "hwklr.db.icourse_client",
                "hwklr.db.icourse_store",
            ),
            excluded_paths=(
                "hwklr/db/icoursedb.py",
                "hwklr/db/icourse_sources.json",
                "hwklr/db/icourse_models.py",
                "hwklr/db/icourse_client.py",
                "hwklr/db/icourse_store.py",
            ),
        ),
        packaging=FeaturePackagingSpec(
            hidden_imports=("greenlet", "pyee", "cryptography", "websocket"),
            collect_submodules=("hwklr.features.icourse",),
            collect_all=("playwright",),
        ),
    ),
    FeatureSpec(
        name="构建",
        module="hwklr.features.build",
        class_name="BuildFeature",
        view_dir="build",
        description="将当前程序导出为可直接运行的分发包，或从模板创建、测试并打包第三方插件。",
        id="build",
        order=90,
        config=FeatureConfigSpec(
            section="build",
            defaults=(
                ("output_dir", ""),
                ("dev_format", "executable"),
                ("plugin_template", ""),
                ("plugin_project", ""),
                ("enabled", True),
            ),
        ),
        meta=FeatureMetaSpec(
            package="BUILD",
            author="Gary",
            update_date="2026-11-03",
            description="将当前程序导出为可直接运行的目录、zip 或可执行文件，并构建插件发布包。",
        ),
        packaging=FeaturePackagingSpec(
            dev_default="dev",
            always_dev=True,
            plugin_template="hwklr/features/build/vendor/plugin-template.zip",
        ),
    ),
)

FEATURE_BY_NAME: Final[dict[str, FeatureSpec]] = {
    spec.name: spec for spec in OFFICIAL_FEATURES
}
FEATURE_BY_ID: Final[dict[str, FeatureSpec]] = {
    spec.stable_id: spec for spec in OFFICIAL_FEATURES
}


def feature_order() -> tuple[FeatureSpec, ...]:
    """按 order 返回官方功能。"""
    return tuple(sorted(OFFICIAL_FEATURES, key=lambda item: item.order))


def official_sections() -> dict[str, str]:
    """返回显示名/稳定 id/别名到配置 section 的映射。"""
    sections: dict[str, str] = {}
    for spec in OFFICIAL_FEATURES:
        if spec.config is None:
            continue
        for name in (spec.name, spec.stable_id, *spec.aliases):
            sections[name] = spec.config.section
    return sections


def feature_config_defaults() -> dict[str, dict[str, Any]]:
    """返回各功能 section 的默认值（不含 build.features）。"""
    result: dict[str, dict[str, Any]] = {}
    for spec in OFFICIAL_FEATURES:
        if spec.config is None:
            continue
        result[spec.config.section] = {
            key: value for key, value in spec.config.defaults
        }
    return result


def build_features_default() -> dict[str, str]:
    """返回 build.features 的默认开发/发布标记。"""
    return {
        spec.name: ("dev" if spec.packaging.always_dev else spec.packaging.dev_default)
        for spec in OFFICIAL_FEATURES
    }


def feature_provider_specs() -> tuple[tuple[str, str], ...]:
    """返回 DbManager 使用的 provider (module, class) 列表。"""
    return tuple(
        (spec.db.provider_module, spec.db.provider_class)
        for spec in OFFICIAL_FEATURES
        if spec.db is not None
    )
