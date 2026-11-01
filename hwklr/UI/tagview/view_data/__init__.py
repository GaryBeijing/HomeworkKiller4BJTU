# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-01 12:40
# 文件名: __init__.py
# 主要用途: 集中登记每个标签页的启动参数；按官方功能清单动态加载，支持裁剪后的导出包。
# 文件版本: 2.1.0
"""标签页启动参数。

``VIEW_PARAMS`` 是标签页的注册表：新增官方功能时，在
:mod:`hwklr.features.manifest` 的 ``OFFICIAL_FEATURES`` 中追加一条，并在
同目录下提供 ``<view_dir>/index.html``、``css/<view_dir>.css``、
``js/<view_dir>.js`` 即可。

功能模块缺失（例如非开发导出时裁掉了 dev 功能）会自动跳过该标签；
设置恒为倒数第二、关于恒为最后，由窗口层再次强制校验。
"""
from __future__ import annotations

from typing import Final, NamedTuple

from hwklr.features import Feature
from hwklr.features.about import AboutFeature
from hwklr.features.manifest import OFFICIAL_FEATURES, FeatureSpec, load_feature_class
from hwklr.features.settings import SettingsFeature

__version__ = "2.1.0"
__author__ = "Gary"
__all__ = [
    "ABOUT_NAME",
    "SETTINGS_NAME",
    "VIEW_PARAMS",
    "ViewParam",
]

SETTINGS_NAME: Final[str] = "设置"
ABOUT_NAME: Final[str] = "关于"


class ViewParam(NamedTuple):
    """单个标签页的启动参数。"""

    function_name: str
    """功能名称，同时作为 :meth:`TagView.load` 的键。"""

    title: str
    """标签栏显示标题。"""

    html: str
    """相对 ``view_data`` 目录的 HTML 路径。"""

    css: tuple[str, ...]
    """相对 ``view_data`` 目录的 CSS 路径元组。"""

    js: tuple[str, ...]
    """相对 ``view_data`` 目录的 JS 路径元组。"""

    feature_cls: type[Feature]
    """该标签对应的功能类。"""

    description: str
    """标签功能说明，用于关于页与标签栏提示。"""


def _feature_param(spec: FeatureSpec) -> ViewParam | None:
    """把功能清单项转换为标签参数。

    Args:
        spec: 官方功能描述。

    Returns:
        标签参数；功能模块被裁剪或不可导入时返回 ``None``。
    """
    feature_cls = load_feature_class(spec.module, spec.class_name)
    if feature_cls is None:
        return None
    return ViewParam(
        function_name=spec.name,
        title=spec.name,
        html="%s/index.html" % spec.view_dir,
        css=("%s/css/%s.css" % (spec.view_dir, spec.view_dir),),
        js=("%s/js/%s.js" % (spec.view_dir, spec.view_dir),),
        feature_cls=feature_cls,  # type: ignore[arg-type]
        description=spec.description,
    )


def _build_view_params() -> dict[str, ViewParam]:
    """按官方清单构建标签注册表。

    Returns:
        名称到标签参数的字典；设置与关于固定在最后。
    """
    params: dict[str, ViewParam] = {}
    for spec in OFFICIAL_FEATURES:
        param: ViewParam | None = _feature_param(spec)
        if param is not None:
            params[spec.name] = param
    params[SETTINGS_NAME] = ViewParam(
        function_name=SETTINGS_NAME,
        title=SETTINGS_NAME,
        html="settings/index.html",
        css=("settings/css/settings.css",),
        js=("settings/js/settings.js",),
        feature_cls=SettingsFeature,
        description="管理账号密码、查看知识库版本与本地服务端口。",
    )
    params[ABOUT_NAME] = ViewParam(
        function_name=ABOUT_NAME,
        title=ABOUT_NAME,
        html="about/index.html",
        css=("about/css/about.css",),
        js=("about/js/about.js",),
        feature_cls=AboutFeature,
        description="查看软件信息、作者、功能列表与使用声明。",
    )
    return params


VIEW_PARAMS: Final[dict[str, ViewParam]] = _build_view_params()
