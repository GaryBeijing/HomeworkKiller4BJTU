# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-01 12:38
# 文件名: devenv.py
# 主要用途: 开发构建包内的开发环境检测与 HwklrVenv 虚拟环境搭建。
# 文件版本: 2.1.2
"""开发构建辅助环境。

导出的开发构建会在“构建”标签页提示用户搭建开发环境：
- 自动寻找本机系统 Python（不会使用包内自带的 python-embed）；
- 在程序同级目录创建 ``HwklrVenv``，用于迁移开发数据；
- 已存在可用环境时直接返回。
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final

__version__ = "2.1.2"
__author__ = "Gary"
__all__ = [
    "app_home",
    "create_dev_venv",
    "find_system_python",
    "venv_path",
    "venv_ready",
]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_VENV_NAME: Final[str] = "HwklrVenv"


def app_home() -> Path:
    """返回程序所在目录（用于放置 HwklrVenv）。

    打包后取可执行文件所在目录；源码运行时取项目根目录；
    python-embed zip 中取 ``app/`` 目录（即 ``main.py`` 所在目录）。

    Returns:
        程序主目录。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _PROJECT_ROOT


def venv_path() -> Path:
    """返回 HwklrVenv 的目标路径。

    Returns:
        虚拟环境目录路径。
    """
    return app_home() / _VENV_NAME


def _venv_python() -> Path:
    """返回虚拟环境中的 Python 解释器路径。

    Returns:
        解释器路径（Windows 为 Scripts/python.exe，其他平台为 bin/python）。
    """
    root: Path = venv_path()
    if sys.platform == "win32":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


def venv_ready() -> bool:
    """判断开发虚拟环境是否已经可用。

    Returns:
        已创建且存在解释器时返回 ``True``。
    """
    return _venv_python().is_file()


def _candidate_commands() -> list[list[str]]:
    """列出可尝试的系统 Python 命令。

    Returns:
        命令参数列表；Windows 优先使用 ``py -3`` 启动器。
    """
    candidates: list[list[str]] = []
    if sys.platform == "win32":
        candidates.append(["py", "-3"])
    candidates.append(["python"])
    candidates.append(["python3"])
    return candidates


def find_system_python() -> tuple[list[str], str] | None:
    """查找本机可用的系统 Python。

    会排除当前进程自身的解释器（开发包内嵌的 python-embed），
    避免用不可迁移的运行时创建虚拟环境。

    Returns:
        ``(命令参数, 解释器路径)``；未找到时返回 ``None``。
    """
    current: Path = Path(sys.executable).resolve()
    for command in _candidate_commands():
        executable: str | None = shutil.which(command[0])
        if executable is None:
            continue
        try:
            result: subprocess.CompletedProcess[str] = subprocess.run(
                [*command, "-c", "import sys; print(sys.executable)"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if sys.platform == "win32"
                    else 0
                ),
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode != 0:
            continue
        lines: list[str] = (result.stdout or "").strip().splitlines()
        resolved: str = lines[-1].strip() if lines else ""
        if not resolved:
            continue
        try:
            resolved_path: Path = Path(resolved).resolve()
        except OSError:
            continue
        if resolved_path == current:
            continue
        return command, resolved
    return None


def create_dev_venv(log: Callable[[str], None] | None = None) -> dict[str, object]:
    """在本机创建 HwklrVenv 开发虚拟环境。

    Args:
        log: 可选的单行日志回调。

    Returns:
        结果字典：``ready``、``path``、``python``、``created``。

    Raises:
        RuntimeError: 未找到系统 Python 或创建失败时抛出。
    """

    def emit(message: str) -> None:
        if callable(log):
            log(message)

    target: Path = venv_path()
    if venv_ready():
        emit("HwklrVenv 已存在，跳过创建。")
        return {
            "ready": True,
            "path": str(target),
            "python": str(_venv_python()),
            "created": False,
        }
    found = find_system_python()
    if found is None:
        raise RuntimeError("无法在此构建开发环境，请安装python后继续")
    command, python_path = found
    emit("检测到系统 Python：%s" % python_path)
    emit("正在创建虚拟环境：%s" % target)
    args: list[str] = [*command, "-m", "venv"]
    if target.exists():
        args.append("--clear")
    args.append(str(target))
    try:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            args,
            cwd=str(app_home()),
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if sys.platform == "win32"
                else 0
            ),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("创建 HwklrVenv 失败：%s" % exc) from exc
    if result.returncode != 0:
        detail: str = (result.stderr or result.stdout or "").strip()
        raise RuntimeError("创建 HwklrVenv 失败：%s" % (detail[-500:] or "未知错误"))
    if not venv_ready():
        raise RuntimeError("HwklrVenv 创建后未找到 Python 解释器")
    emit("HwklrVenv 创建完成：%s" % target)
    return {
        "ready": True,
        "path": str(target),
        "python": str(_venv_python()),
        "created": True,
    }
