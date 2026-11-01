# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-01 12:38
# 最后更新: 2026-11-01 13:05
# 文件名: devenv.py
# 主要用途: 开发构建包内的开发环境检测、HwklrVenv 创建与源码迁移。
# 文件版本: 2.1.3
"""开发构建辅助环境。

导出的开发构建会在“构建”标签页提示用户搭建开发环境：
- 自动寻找本机系统 Python（不会使用包内自带的 python-embed）；
- 在程序目录外侧创建 ``HwklrVenv``；
- 创建后把开发源码（``source-v<版本>.zip`` 或本地源码）抽取到
  ``HwklrVenv/HwklrSource``，使代码位于虚拟环境内部；
- 已存在可用环境时直接返回。
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Final

__version__ = "2.1.3"
__author__ = "Gary"
__all__ = [
    "app_home",
    "create_dev_venv",
    "dev_env_ready",
    "find_system_python",
    "source_path",
    "source_ready",
    "venv_path",
    "venv_ready",
]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_VENV_NAME: Final[str] = "HwklrVenv"
_SOURCE_DIR_NAME: Final[str] = "HwklrSource"


def app_home() -> Path:
    """返回程序所在目录（HwklrVenv 放在这里）。

    打包后取可执行文件所在目录；python-embed zip 中取 ``app/`` 的上级
    目录（含 ``start.bat`` / ``BUILD_INFO.json`` 的位置）；源码运行取项目根目录。

    Returns:
        程序主目录。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    parent: Path = _PROJECT_ROOT.parent
    if (
        (parent / "start.bat").is_file()
        or (parent / "BUILD_INFO.json").is_file()
    ):
        return parent
    return _PROJECT_ROOT


def venv_path() -> Path:
    """返回 HwklrVenv 的目标路径。

    Returns:
        虚拟环境目录路径。
    """
    return app_home() / _VENV_NAME


def source_path() -> Path:
    """返回迁移到虚拟环境内部的源码目录。

    Returns:
        ``HwklrVenv/HwklrSource`` 路径。
    """
    return venv_path() / _SOURCE_DIR_NAME


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
    """判断虚拟环境解释器是否已经可用。

    Returns:
        已创建且存在解释器时返回 ``True``。
    """
    return _venv_python().is_file()


def source_ready() -> bool:
    """判断源码是否已迁移到虚拟环境内部。

    Returns:
        ``HwklrSource/main.py`` 与 ``HwklrSource/hwklr`` 均存在时返回 ``True``。
    """
    root: Path = source_path()
    return (root / "main.py").is_file() and (root / "hwklr").is_dir()


def dev_env_ready() -> bool:
    """判断开发环境（虚拟环境 + 内部源码）是否完整。

    Returns:
        两者都就绪时返回 ``True``。
    """
    return venv_ready() and source_ready()


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


def _find_source_archive() -> Path | None:
    """查找开发构建自带的源码归档。

    Returns:
        最新的 ``source-v*.zip``；未找到时返回 ``None``。
    """
    candidates: list[Path] = []
    seen: set[Path] = set()
    for directory in (app_home(), _PROJECT_ROOT):
        try:
            resolved: Path = directory.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if not resolved.is_dir():
            continue
        candidates.extend(resolved.glob("source-v*.zip"))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime)


def _extract_source_archive(archive: Path, target: Path, emit: Callable[[str], None]) -> None:
    """把源码归档解压到虚拟环境内部目录。

    Args:
        archive: 源码 zip 路径。
        target: 目标目录（``HwklrVenv/HwklrSource``）。
        emit: 日志回调。

    Raises:
        RuntimeError: 压缩包损坏或包含越界路径时抛出。
    """
    emit("正在把源码迁移到虚拟环境：%s" % target)
    root: Path = target.resolve()
    try:
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                destination: Path = (target / member.filename).resolve()
                if not destination.is_relative_to(root):
                    raise RuntimeError("源码归档包含非法路径：%s" % member.filename)
            bundle.extractall(target)
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError("解压源码归档失败：%s" % exc) from exc


def _copy_local_sources(target: Path, emit: Callable[[str], None]) -> bool:
    """在没有源码归档时，从本地源码目录复制代码。

    Args:
        target: 目标目录。
        emit: 日志回调。

    Returns:
        找到并复制了本地源码返回 ``True``。
    """
    main_file: Path = _PROJECT_ROOT / "main.py"
    package_dir: Path = _PROJECT_ROOT / "hwklr"
    if not main_file.is_file() or not package_dir.is_dir():
        return False
    emit("未找到源码归档，改用本地源码：%s" % _PROJECT_ROOT)
    shutil.copy2(main_file, target / "main.py")
    requirements: Path = _PROJECT_ROOT / "requirements.txt"
    if requirements.is_file():
        shutil.copy2(requirements, target / "requirements.txt")

    def ignore(directory: str, names: list[str]) -> set[str]:
        """忽略缓存、测试与下载缓存。

        Args:
            directory: 当前目录。
            names: 目录内名称。

        Returns:
            需要忽略的名称集合。
        """
        ignored: set[str] = set()
        for name in names:
            path: Path = Path(directory) / name
            try:
                relative: str = path.relative_to(_PROJECT_ROOT).as_posix()
            except ValueError:
                continue
            if name == "__pycache__" or name.endswith((".pyc", ".pyo")):
                ignored.add(name)
            elif relative.startswith("hwklr/features/build/vendor"):
                ignored.add(name)
            elif "tests" in path.parts or name.startswith("test_"):
                ignored.add(name)
        return ignored

    shutil.copytree(package_dir, target / "hwklr", ignore=ignore)
    return True


def _prepare_sources(emit: Callable[[str], None]) -> tuple[Path, bool]:
    """确保源码位于虚拟环境内部。

    Args:
        emit: 日志回调。

    Returns:
        ``(源码目录, 是否本次新抽取)``。

    Raises:
        RuntimeError: 找不到可用源码时抛出。
    """
    target: Path = source_path()
    if source_ready():
        emit("源码已在虚拟环境内：%s" % target)
        return target, False
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    archive: Path | None = _find_source_archive()
    if archive is not None:
        _extract_source_archive(archive, target, emit)
    elif not _copy_local_sources(target, emit):
        raise RuntimeError("未找到开发源码归档，无法把代码迁移到 HwklrVenv")
    if not source_ready():
        raise RuntimeError("源码迁移后未找到 main.py 或 hwklr 目录")
    emit("源码已迁移到虚拟环境：%s" % target)
    return target, True


def create_dev_venv(log: Callable[[str], None] | None = None) -> dict[str, object]:
    """创建 HwklrVenv，并把开发源码迁移到虚拟环境内部。

    Args:
        log: 可选的单行日志回调。

    Returns:
        结果字典：``ready``、``path``、``source``、``python``、
        ``created``、``code_extracted``。

    Raises:
        RuntimeError: 未找到系统 Python、创建失败或源码迁移失败时抛出。
    """

    def emit(message: str) -> None:
        if callable(log):
            log(message)

    target: Path = venv_path()
    created: bool = False
    if venv_ready():
        emit("HwklrVenv 已存在，复用现有虚拟环境。")
    else:
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
            raise RuntimeError(
                "创建 HwklrVenv 失败：%s" % (detail[-500:] or "未知错误")
            )
        if not venv_ready():
            raise RuntimeError("HwklrVenv 创建后未找到 Python 解释器")
        created = True
        emit("HwklrVenv 创建完成：%s" % target)

    source, code_extracted = _prepare_sources(emit)
    return {
        "ready": dev_env_ready(),
        "path": str(target),
        "source": str(source),
        "python": str(_venv_python()),
        "created": created,
        "code_extracted": code_extracted,
    }
