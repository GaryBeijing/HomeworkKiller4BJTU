# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-08 13:26
# 文件名: __init__.py
# 主要用途: hwklr 主包元数据与全局应用信息（V3.1.0，支持导出时注入版本、名称、图标与开发标记）。
# 文件版本: 3.1.0
"""HomeworkKiller4BJTU 主包。

本包只声明项目级元数据，具体功能拆分为：
- ``hwklr.features``：功能实现（Feature 抽象与各功能类）。
- ``hwklr.db``：外部 ``db/`` 数据文件的 provider 与管理器。
- ``hwklr.runtime_data``：随包分发的知识库源文件。
- ``hwklr.UI``：pywebview 窗口、标签抽象与前端资源。
"""
from __future__ import annotations

from pathlib import Path

# 导出构建会在打包前生成 _build_info.py，用于覆盖版本、名称、图标与开发标记；
# 源码运行时该文件不存在，使用项目默认值。
__version__: str = "3.1.0"
DEV_BUILD: bool = False
_EXPORT_NAME: str = ""
_ICON_RELATIVE: str = ""
try:
    from . import _build_info
except ImportError:  # pragma: no cover - 源码运行分支
    pass
else:
    __version__ = str(getattr(_build_info, "EXPORT_VERSION", __version__))
    _EXPORT_NAME = str(getattr(_build_info, "EXPORT_NAME", "") or "").strip()
    DEV_BUILD = bool(getattr(_build_info, "DEV_BUILD", False))
    _ICON_RELATIVE = str(getattr(_build_info, "ICON_PATH", "") or "").strip()

__author__ = "Gary"
__all__ = [
    "__version__",
    "__author__",
    "APP_NAME",
    "APP_TITLE",
    "APP_ICON",
    "APP_AUTHORS",
    "APP_DESCRIPTION",
    "APP_DISCLAIMER",
    "DEV_BUILD",
]

APP_NAME: str = _EXPORT_NAME or "HomeworkKiller4BJTU"
APP_TITLE: str = _EXPORT_NAME or "HomeworkKiller4BJTU · 作业助手"
APP_ICON: str = ""
if _ICON_RELATIVE:
    _icon_candidate: Path = Path(__file__).resolve().parent.parent / _ICON_RELATIVE
    if _icon_candidate.is_file():
        APP_ICON = str(_icon_candidate)
APP_AUTHORS: tuple[str, ...] = ("Gary", "PhiloK (Gary remastered)（高铁纵横）")
APP_DESCRIPTION: str = (
    "面向北京交通大学学生的辅助工具：提供高铁答题辅助与 C 语言程序设计学习支持，"
    "在同学做题需要帮助时协助理解题目、梳理思路，以减轻学习压力。"
)
APP_DISCLAIMER: str = (
    "本工具仅供个人账号学习辅助使用，请遵守学校考试纪律、课程 AI 使用规定与相关规章制度；"
    "题解模式会直接生成并提交完整代码，请仅在十分需要真实实例的情况下酌情使用，否则请使用启发模式自行完成。"
    "使用本工具产生的后果由使用者自行承担。"
)
