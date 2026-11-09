# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-09 19:05
# 文件名: pyi_rth_unblock_motw.py
# 主要用途: PyInstaller 运行时钩子：启动时移除分发包内 DLL/EXE 的“来自网络”标记，避免 .NET/pythonnet 拒绝加载 Python.Runtime.dll。
# 文件版本: 1.0.0
"""PyInstaller 运行时钩子：解除分发包内 DLL/EXE 的 Mark-of-the-Web。

Windows 会为从网络下载的 zip 解压出的文件写入 ``Zone.Identifier`` 备用数据流。
.NET 的 ``Assembly.LoadFrom`` 默认拒绝加载带该标记的程序集，导致
``clr_loader`` 无法解析 ``Python.Runtime.Loader.Initialize``，pywebview 启动失败。

本钩子在 ``main.py`` 之前执行（PyInstaller ``--runtime-hook`` 的保证），
遍历 ``sys._MEIPASS``（目录版即 ``_internal``），删除 ``.dll`` / ``.exe``
上的 ``Zone.Identifier`` 流。删除备用数据流只需要当前用户对文件有写权限，
不会触发 UAC，也不需要管理员权限。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

__version__ = "1.0.0"
__author__ = "Gary"
__all__ = ["unblock_tree"]

_TARGET_SUFFIXES: tuple[str, ...] = (".dll", ".exe")
_ZONE_STREAM_SUFFIX: str = ":Zone.Identifier"


def unblock_tree(root: Path) -> int:
    """移除目录树中所有 DLL/EXE 的 ``Zone.Identifier`` 备用数据流。

    Args:
        root: 待处理的根目录，通常是 ``sys._MEIPASS``。

    Returns:
        成功移除标记的文件数量。没有标记、无权限或文件已被删除时跳过。
    """
    if sys.platform != "win32" or not root.is_dir():
        return 0

    removed: int = 0
    # 关键步骤：只处理 .dll/.exe；.NET 拒绝加载的正是这些程序集/可执行文件。
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            if not filename.lower().endswith(_TARGET_SUFFIXES):
                continue
            path: str = os.path.join(dirpath, filename)
            try:
                # 关键步骤：删除备用数据流；流不存在时抛 FileNotFoundError，
                # 统一按 OSError 跳过，不影响应用启动。
                os.remove(path + _ZONE_STREAM_SUFFIX)
            except OSError:
                continue
            removed += 1
    return removed


def _run_hook() -> None:
    """在 PyInstaller 冻结环境中执行清理。"""
    bundle_root: Path = Path(
        getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)
    )
    unblock_tree(bundle_root)


# 关键步骤：仅在实际打包运行时自动执行；源码导入（测试）时不产生副作用。
if getattr(sys, "frozen", False):
    _run_hook()
