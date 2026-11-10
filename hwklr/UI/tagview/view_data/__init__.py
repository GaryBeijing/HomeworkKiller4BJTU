# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-10 23:59
# 文件名: __init__.py
# 主要用途: 集中登记每个标签页的启动参数；支持官方功能裁剪与运行期第三方扩展注册。
# 文件版本: 4.4.2
"""标签页启动参数。

``VIEW_PARAMS`` 是标签页的注册表：新增官方功能时，在
:mod:`hwklr.features.manifest` 的 ``OFFICIAL_FEATURES`` 中追加一条，并在
同目录下提供 ``<view_dir>/index.html``、``css/<view_dir>.css``、
``js/<view_dir>.js`` 即可。

功能模块缺失（例如非开发导出时裁掉了 dev 功能）会自动跳过该标签；
设置恒为倒数第二、关于恒为最后，由窗口层再次强制校验。
"""
from __future__ import annotations

import threading
from typing import Final, NamedTuple

from hwklr.features import Feature
from hwklr.features.about import AboutFeature
from hwklr.feature_specs import feature_order
from hwklr.features.manifest import FeatureSpec, load_feature_class
from hwklr.features.settings import SettingsFeature

__version__ = "4.4.2"
__author__ = "Gary"
__all__ = [
    "ABOUT_NAME",
    "SETTINGS_NAME",
    "VIEW_PARAMS",
    "ViewParam",
    "all_view_params",
    "get_view_param",
    "register_extension_param",
    "unregister_extension_param",
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

    base_url: str = "/view_data/"
    """前端资源 URL 前缀；第三方扩展为 ``/extensions/<id>/``。"""

    resource_root: str = ""
    """本地资源根目录；空字符串表示官方 ``view_data`` 目录。"""

    order: int = 0
    """标签排序值；小者在前，设置与关于固定为 1000/1010。"""

    actions: tuple[dict[str, object], ...] = ()
    """manifest 声明的动作元数据；仅第三方扩展使用，不作为调用白名单。"""


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
    assets = spec.assets
    html = (
        assets.html
        if assets is not None and assets.html
        else "%s/index.html" % spec.view_dir
    )
    css = (
        assets.css
        if assets is not None and assets.css
        else ("%s/css/%s.css" % (spec.view_dir, spec.view_dir),)
    )
    js = (
        assets.js
        if assets is not None and assets.js
        else ("%s/js/%s.js" % (spec.view_dir, spec.view_dir),)
    )
    return ViewParam(
        function_name=spec.name,
        title=spec.name,
        html=html,
        css=css,
        js=js,
        feature_cls=feature_cls,  # type: ignore[arg-type]
        description=spec.description,
        order=spec.order,
    )


def _build_view_params() -> dict[str, ViewParam]:
    """按官方清单构建标签注册表。

    Returns:
        名称到标签参数的字典；设置与关于固定在最后。
    """
    params: dict[str, ViewParam] = {}
    for spec in feature_order():
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
        order=1000,
    )
    params[ABOUT_NAME] = ViewParam(
        function_name=ABOUT_NAME,
        title=ABOUT_NAME,
        html="about/index.html",
        css=("about/css/about.css",),
        js=("about/js/about.js",),
        feature_cls=AboutFeature,
        description="查看软件信息、作者、功能列表与使用声明。",
        order=1010,
    )
    return params


VIEW_PARAMS: dict[str, ViewParam] = _build_view_params()
# 运行期注册的第三方扩展开关；官方清单仍以 VIEW_PARAMS 为唯一静态真相。
_EXTENSION_PARAMS: dict[str, ViewParam] = {}
_EXTENSION_PARAMS_LOCK: Final[threading.RLock] = threading.RLock()


def register_extension_param(param: ViewParam) -> None:
    """注册一个第三方扩展标签参数。

    Args:
        param: 扩展标签参数。
    """
    with _EXTENSION_PARAMS_LOCK:
        _EXTENSION_PARAMS[param.function_name] = param


def unregister_extension_param(name: str) -> None:
    """移除一个运行期扩展标签参数。

    Args:
        name: 标签名称。
    """
    with _EXTENSION_PARAMS_LOCK:
        _EXTENSION_PARAMS.pop(str(name or ""), None)


def all_view_params() -> dict[str, ViewParam]:
    """返回官方与扩展合并后的标签参数。

    Returns:
        名称到标签参数的字典。
    """
    with _EXTENSION_PARAMS_LOCK:
        merged: dict[str, ViewParam] = dict(VIEW_PARAMS)
        merged.update(_EXTENSION_PARAMS)
    # dict 保持插入顺序；sorted 稳定，因此同 order 的标签仍按注册先后排列。
    return dict(sorted(merged.items(), key=lambda item: item[1].order))


def get_view_param(name: str) -> ViewParam | None:
    """按名称读取标签参数。

    Args:
        name: 标签名称。

    Returns:
        标签参数；不存在时返回 ``None``。
    """
    param: ViewParam | None = VIEW_PARAMS.get(name)
    if param is not None:
        return param
    with _EXTENSION_PARAMS_LOCK:
        return _EXTENSION_PARAMS.get(name)
