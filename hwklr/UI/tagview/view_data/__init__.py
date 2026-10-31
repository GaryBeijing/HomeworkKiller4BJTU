# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-01 00:01
# 文件名: __init__.py
# 主要用途: 集中登记每个标签页的启动参数（标题、资源路径、功能类）。
# 文件版本: 2.0.0
"""标签页启动参数。

``VIEW_PARAMS`` 是标签页的唯一注册表：新增功能时，在此追加一条
:class:`ViewParam`，并在同目录下提供对应的 HTML/CSS/JS 资源即可。
标签顺序中“设置”恒为倒数第二、“关于”恒为最后，由窗口层再次强制校验。
"""
from __future__ import annotations

from typing import Final, NamedTuple

from hwklr.features import (
    AboutFeature,
    CProgrammingFeature,
    Feature,
    HSRFeature,
    SettingsFeature,
)

__version__ = "2.0.0"
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


VIEW_PARAMS: Final[dict[str, ViewParam]] = {
    "高铁纵横": ViewParam(
        function_name="高铁纵横",
        title="高铁纵横",
        html="hsr/index.html",
        css=("hsr/css/hsr.css",),
        js=("hsr/js/hsr.js",),
        feature_cls=HSRFeature,
        description="登录高铁答题系统，按题库自动匹配答案并提交考试。",
    ),
    "C程序设计": ViewParam(
        function_name="C程序设计",
        title="C程序设计",
        html="cprog/index.html",
        css=("cprog/css/cprog.css",),
        js=("cprog/js/cprog.js",),
        feature_cls=CProgrammingFeature,
        description="CITEL 课程题目辅助：启发模式逐步讲解，题解模式生成并提交参考实现。",
    ),
    SETTINGS_NAME: ViewParam(
        function_name=SETTINGS_NAME,
        title=SETTINGS_NAME,
        html="settings/index.html",
        css=("settings/css/settings.css",),
        js=("settings/js/settings.js",),
        feature_cls=SettingsFeature,
        description="管理账号密码、查看知识库版本与本地服务端口。",
    ),
    ABOUT_NAME: ViewParam(
        function_name=ABOUT_NAME,
        title=ABOUT_NAME,
        html="about/index.html",
        css=("about/css/about.css",),
        js=("about/js/about.js",),
        feature_cls=AboutFeature,
        description="查看软件信息、作者、功能列表与使用声明。",
    ),
}
