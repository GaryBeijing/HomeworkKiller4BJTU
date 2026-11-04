# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-01 12:38
# 最后更新: 2026-11-04 11:55
# 文件名: devenv.py
# 主要用途: 开发构建包内的开发环境检测、HwklrVenv 创建、V3 源码布局迁移、依赖安装与插件模板分发。
# 文件版本: 3.0.1
"""开发构建辅助环境。

导出的开发构建会在“构建”标签页提示用户搭建开发环境：
- 自动寻找本机系统 Python（不会使用包内自带的 python-embed）；
- 在程序目录外侧创建 ``HwklrVenv``；
- 把 ``legacy/``、``Reference/``、``main.py``、``requirements.txt``、
  ``README.md``、``LICENSE`` 解压到虚拟环境根目录，把 ``hwklr/`` 解压到
  ``HwklrVenv/Lib/``；
- 用虚拟环境的 pip 从清华源安装 ``requirements.txt``；
- 生成 ``启动程序.bat`` / ``调试程序.bat``，并把插件工程模板放到 ``vendor/``。
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

__version__ = "3.0.1"
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


def _resolve_project_root() -> Path:
    """定位含 ``main.py`` 的项目根目录（兼容 HwklrVenv 的 ``Lib/`` 布局）。

    Returns:
        项目根目录。
    """
    current: Path = Path(__file__).resolve()
    for candidate in (current.parents[3], current.parents[4]):
        if (candidate / "main.py").is_file():
            return candidate
    return current.parents[3]


_PROJECT_ROOT: Final[Path] = _resolve_project_root()
_VENV_NAME: Final[str] = "HwklrVenv"
_PIP_MIRROR: Final[str] = "https://pypi.tuna.tsinghua.edu.cn/simple"
_TEMPLATE_NAME: Final[str] = "plugin-template.zip"
_ROOT_ITEMS: Final[tuple[str, ...]] = (
    "main.py",
    "requirements.txt",
    "legacy",
    "Reference",
)


def app_home() -> Path:
    """返回程序所在目录（HwklrVenv 放在这里）。

    打包后取可执行文件所在目录；python-embed zip 中取 ``app/`` 的上级
    目录（含 ``start.bat`` / ``BUILD_INFO.json`` 的位置）；源码运行取项目根目录。

    Returns:
        程序主目录。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # 源码仓库 / HwklrVenv：含 pyvenv.cfg 与 main.py 的目录。
    for candidate in (_PROJECT_ROOT, _PROJECT_ROOT.parent):
        if (candidate / "pyvenv.cfg").is_file() and (
            candidate / "main.py"
        ).is_file():
            return candidate
    # 开发包：start.bat / BUILD_INFO.json 所在目录。
    for candidate in (
        _PROJECT_ROOT,
        _PROJECT_ROOT.parent,
        _PROJECT_ROOT.parent.parent,
    ):
        if (candidate / "start.bat").is_file() or (
            candidate / "BUILD_INFO.json"
        ).is_file():
            return candidate
    return _PROJECT_ROOT


def venv_path() -> Path:
    """返回开发虚拟环境路径。

    源码运行时项目根目录本身是虚拟环境，直接复用；开发产物中使用
    ``HwklrVenv``。

    Returns:
        虚拟环境目录路径。
    """
    home: Path = app_home()
    if (home / "pyvenv.cfg").is_file():
        return home
    return home / _VENV_NAME


def source_path() -> Path:
    """返回开发源码所在的虚拟环境根目录。

    V3 起源码不再集中放在 ``HwklrSource``：``main.py`` 等位于虚拟环境根目录，
    ``hwklr/`` 位于 ``Lib/``。

    Returns:
        ``HwklrVenv`` 路径。
    """
    return venv_path()


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
    """判断源码是否已按 V3 布局迁移到虚拟环境。

    Returns:
        根目录存在 ``main.py`` 且 ``Lib/hwklr/__init__.py`` 存在时返回 ``True``。
    """
    root: Path = source_path()
    return (root / "main.py").is_file() and (
        root / "Lib" / "hwklr" / "__init__.py"
    ).is_file()


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
    for directory in (
        app_home(),
        app_home().parent,
        _PROJECT_ROOT,
        _PROJECT_ROOT.parent,
    ):
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


def _archive_destination(root: Path, member_name: str) -> Path | None:
    """计算源码归档成员在虚拟环境中的目标路径。

    Args:
        root: 虚拟环境根目录。
        member_name: zip 内成员名。

    Returns:
        目标路径；不属于开发源码时返回 ``None``。
    """
    normalized: str = member_name.replace("\\", "/")
    parts: list[str] = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        return None
    if parts[0] == "hwklr":
        return root / "Lib" / Path(*parts)
    if parts[0] in ("legacy", "Reference"):
        return root / Path(*parts)
    if len(parts) == 1 and parts[0] in (
        "main.py",
        "requirements.txt",
        "README.md",
        "LICENSE",
    ):
        return root / parts[0]
    return None


def _extract_source_archive(archive: Path, target: Path, emit: Callable[[str], None]) -> None:
    """把 V3 源码归档按新布局解压到虚拟环境。

    Args:
        archive: 源码 zip 路径。
        target: 虚拟环境根目录。
        emit: 日志回调。

    Raises:
        RuntimeError: 压缩包损坏或包含越界路径时抛出。
    """
    emit("正在把源码迁移到虚拟环境：%s" % target)
    root: Path = target.resolve()
    try:
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                if member.is_dir():
                    continue
                destination: Path | None = _archive_destination(target, member.filename)
                if destination is None:
                    continue
                resolved: Path = destination.resolve()
                if not resolved.is_relative_to(root):
                    raise RuntimeError("源码归档包含非法路径：%s" % member.filename)
                resolved.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, resolved.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError("解压源码归档失败：%s" % exc) from exc


def _copy_local_sources(target: Path, emit: Callable[[str], None]) -> bool:
    """在没有源码归档时，从本地源码目录按 V3 布局复制代码。

    Args:
        target: 虚拟环境根目录。
        emit: 日志回调。

    Returns:
        找到并复制了本地源码返回 ``True``。
    """
    main_file: Path = _PROJECT_ROOT / "main.py"
    package_dir: Path = _PROJECT_ROOT / "hwklr"
    if not package_dir.is_dir():
        package_dir = _PROJECT_ROOT / "Lib" / "hwklr"
    if not main_file.is_file() or not package_dir.is_dir():
        return False
    emit("未找到源码归档，改用本地源码：%s" % _PROJECT_ROOT)
    shutil.copy2(main_file, target / "main.py")
    for name in ("requirements.txt", "README.md", "LICENSE"):
        source_file: Path = _PROJECT_ROOT / name
        if source_file.is_file():
            shutil.copy2(source_file, target / name)
    for name in ("legacy", "Reference"):
        source: Path = _PROJECT_ROOT / name
        if source.is_dir():
            shutil.copytree(source, target / name, dirs_exist_ok=True)

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
            if name == "__pycache__" or name.endswith((".pyc", ".pyo")):
                ignored.add(name)
                continue
            if name == "vendor" and path.parent.name == "build":
                # 下载缓存与模板都不从本地源码目录复制；模板由 _copy_plugin_template 单独处理。
                ignored.add(name)
                continue
            if "tests" in path.parts or name.startswith("test_"):
                ignored.add(name)
        return ignored

    shutil.copytree(
        package_dir, target / "Lib" / "hwklr", ignore=ignore, dirs_exist_ok=True
    )
    return True


def _site_packages(root: Path) -> Path:
    """返回虚拟环境的 site-packages 目录。

    Args:
        root: 虚拟环境根目录。

    Returns:
        site-packages 路径。
    """
    if (root / "Lib").is_dir():
        return root / "Lib" / "site-packages"
    candidates: list[Path] = sorted((root / "lib").glob("python*/site-packages"))
    return candidates[0] if candidates else root / "Lib" / "site-packages"


def _write_dev_path(root: Path, emit: Callable[[str], None]) -> None:
    """写入 .pth，使 ``Lib/hwklr`` 可以被虚拟环境导入。

    Args:
        root: 虚拟环境根目录。
        emit: 日志回调。
    """
    site: Path = _site_packages(root)
    site.mkdir(parents=True, exist_ok=True)
    pth: Path = site / "_hwklr_dev.pth"
    pth.write_text("..\n", encoding="ascii")
    emit("已写入开发路径：%s" % pth)


def _write_start_bats(root: Path, emit: Callable[[str], None]) -> None:
    """生成启动与调试用的批处理文件。

    Args:
        root: 虚拟环境根目录。
        emit: 日志回调。
    """
    if sys.platform == "win32":
        pythonw: str = "%~dp0Scripts\\pythonw.exe"
        python_exe: str = "%~dp0Scripts\\python.exe"
    else:
        pythonw = "%~dp0bin/python"
        python_exe = pythonw
    launch: str = (
        "@echo off\r\n"
        "setlocal\r\n"
        "cd /d \"%~dp0\"\r\n"
        "\"" + pythonw + "\" \"%~dp0main.py\"\r\n"
    )
    debug: str = (
        "@echo off\r\n"
        "setlocal\r\n"
        "cd /d \"%~dp0\"\r\n"
        "\"" + python_exe + "\" \"%~dp0main.py\"\r\n"
        "echo.\r\n"
        "pause\r\n"
    )
    # #newline="" 防止 Windows 文本模式把已有的 \r\n 再翻译一次。
    with (root / "启动程序.bat").open("w", encoding="ascii", newline="") as handle:
        handle.write(launch)
    with (root / "调试程序.bat").open("w", encoding="ascii", newline="") as handle:
        handle.write(debug)
    emit("已生成启动程序.bat / 调试程序.bat")


def _copy_plugin_template(root: Path, emit: Callable[[str], None]) -> Path | None:
    """把插件工程模板复制到虚拟环境的 vendor/。

    Args:
        root: 虚拟环境根目录。
        emit: 日志回调。

    Returns:
        模板 zip 路径；未找到时返回 ``None``。
    """
    candidates: tuple[Path, ...] = (
        app_home() / "vendor" / _TEMPLATE_NAME,
        _PROJECT_ROOT / "hwklr" / "features" / "build" / "vendor" / _TEMPLATE_NAME,
        _PROJECT_ROOT
        / "Lib"
        / "hwklr"
        / "features"
        / "build"
        / "vendor"
        / _TEMPLATE_NAME,
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        vendor: Path = root / "vendor"
        vendor.mkdir(parents=True, exist_ok=True)
        target: Path = vendor / _TEMPLATE_NAME
        try:
            same_file: bool = candidate.resolve() == target.resolve()
        except OSError:
            same_file = False
        if not same_file:
            shutil.copy2(candidate, target)
        emit("插件工程模板：%s" % target)
        return target
    return None


def _pip_install(root: Path, emit: Callable[[str], None]) -> None:
    """用虚拟环境的 pip 从清华源安装 requirements.txt。

    Args:
        root: 虚拟环境根目录。
        emit: 日志回调。

    Raises:
        RuntimeError: pip 执行失败时抛出。
    """
    requirements: Path = root / "requirements.txt"
    if not requirements.is_file():
        emit("未找到 requirements.txt，跳过依赖安装。")
        return
    emit("正在从清华源安装依赖：%s" % requirements)
    command: list[str] = [
        str(_venv_python()),
        "-m",
        "pip",
        "install",
        "-r",
        str(requirements),
        "-i",
        _PIP_MIRROR,
        "--disable-pip-version-check",
        "--no-input",
    ]
    try:
        process: subprocess.Popen[str] = subprocess.Popen(
            command,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if sys.platform == "win32"
                else 0
            ),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("启动 pip 失败：%s" % exc) from exc
    assert process.stdout is not None
    tail: list[str] = []
    for raw_line in process.stdout:
        line: str = raw_line.rstrip()
        if not line:
            continue
        tail.append(line)
        if len(tail) > 40:
            del tail[: len(tail) - 40]
        emit(line)
    code: int = process.wait()
    if code != 0:
        raise RuntimeError(
            "安装依赖失败（退出码 %d）：%s" % (code, "\n".join(tail[-8:]))
        )
    emit("依赖安装完成。")


def _prepare_sources(emit: Callable[[str], None]) -> tuple[Path, bool]:
    """确保源码按 V3 布局位于虚拟环境内部。

    Args:
        emit: 日志回调。

    Returns:
        ``(虚拟环境根目录, 是否本次新抽取)``。

    Raises:
        RuntimeError: 找不到可用源码时抛出。
    """
    target: Path = source_path()
    if source_ready():
        emit("源码已在虚拟环境内：%s" % target)
        _write_dev_path(target, emit)
        return target, False
    target.mkdir(parents=True, exist_ok=True)
    archive: Path | None = _find_source_archive()
    if archive is not None:
        _extract_source_archive(archive, target, emit)
    elif not _copy_local_sources(target, emit):
        raise RuntimeError("未找到开发源码归档，无法把代码迁移到 HwklrVenv")
    if not source_ready():
        raise RuntimeError("源码迁移后未找到 main.py 或 Lib/hwklr 目录")
    _write_dev_path(target, emit)
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
    # #V3：依赖安装、启动脚本与插件模板都放在虚拟环境内部。
    _pip_install(target, emit)
    template: Path | None = _copy_plugin_template(target, emit)
    _write_start_bats(target, emit)
    (target / "extension").mkdir(parents=True, exist_ok=True)
    return {
        "ready": dev_env_ready(),
        "path": str(target),
        "source": str(source),
        "python": str(_venv_python()),
        "created": created,
        "code_extracted": code_extracted,
        "template": str(template) if template is not None else "",
    }
