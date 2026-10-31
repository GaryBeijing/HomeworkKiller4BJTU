# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-01 00:01
# 文件名: __init__.py
# 主要用途: hwklr 主包元数据与全局应用信息（V2）。
# 文件版本: 2.0.0
"""HomeworkKiller4BJTU 主包。

本包只声明项目级元数据，具体功能拆分为：
- ``hwklr.features``：功能实现（Feature 抽象与各功能类）。
- ``hwklr.runtime_data``：按功能分版本存放的知识库读取接口。
- ``hwklr.UI``：pywebview 窗口、标签抽象与前端资源。
"""
from __future__ import annotations

__version__ = "2.0.0"
__author__ = "Gary"
__all__ = [
    "__version__",
    "__author__",
    "APP_NAME",
    "APP_TITLE",
    "APP_AUTHORS",
    "APP_DESCRIPTION",
    "APP_DISCLAIMER",
]

APP_NAME: str = "HomeworkKiller4BJTU"
APP_TITLE: str = "HomeworkKiller4BJTU · 作业助手"
APP_AUTHORS: tuple[str, ...] = ("Gary", "PhiloK（高铁纵横）")
APP_DESCRIPTION: str = (
    "面向北京交通大学学生的辅助工具：提供高铁答题辅助与 C 语言程序设计学习支持，"
    "在同学做题需要帮助时协助理解题目、梳理思路，以减轻学习压力。"
)
APP_DISCLAIMER: str = (
    "本工具仅供个人账号学习辅助使用，请遵守学校考试纪律、课程 AI 使用规定与相关规章制度；"
    "题解模式会直接生成并提交完整代码，请仅在十分需要真实实例的情况下酌情使用，否则请使用启发模式自行完成。"
    "使用本工具产生的后果由使用者自行承担。"
)
