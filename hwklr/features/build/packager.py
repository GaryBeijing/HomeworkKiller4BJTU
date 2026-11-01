# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-01 12:40
# 最后更新: 2026-11-01 13:05
# 文件名: packager.py
# 主要用途: 构建功能的打包实现：图标/名称/四段版本资源、源码裁剪、源码归档、PyInstaller 与 python-embed zip。
# 文件版本: 2.1.3
"""构建打包实现。

构建过程不依赖 UI，可独立调用 :func:`build_package`：
- **非开发构建**：裁剪掉配置为 dev 的功能与构建标签，使用 PyInstaller
  ``--onedir --windowed --optimize 2`` 生成多文件目录，启动更快、体积更小；
- **开发构建 + executable**：保留全部功能与文档，使用 PyInstaller 目录版并显示终端；
- **开发构建 + zip**：从阿里云镜像下载 64 位 python-embed，复制当前虚拟环境的
  site-packages，生成双击即可运行的 zip 分发包。

所有输出默认位于项目根目录 ``build/``，不会包含用户 ``config.json``。
"""
from __future__ import annotations

import base64
import importlib.metadata
import io
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Final, NamedTuple

from hwklr.features.manifest import OFFICIAL_FEATURES, FeatureSpec

__version__ = "2.1.3"
__author__ = "Gary"
__all__ = [
    "APP_EXE_NAME",
    "BuildError",
    "PYTHON_EMBED_MIRROR",
    "VERSION_PATTERN",
    "build_package",
    "python_embed_url",
    "pyinstaller_version",
    "resolve_output_dir",
    "safe_file_name",
]

APP_EXE_NAME: Final[str] = "HomeworkKiller4BJTU"
PYTHON_EMBED_MIRROR: Final[str] = (
    "https://mirrors.aliyun.com/python-release/windows"
)
VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\d+\.\d+\.\d+(?:\.\d+)?$"
)
_INVALID_FILENAME: Final[re.Pattern[str]] = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES: Final[frozenset[str]] = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {"COM%d" % index for index in range(1, 10)}
    | {"LPT%d" % index for index in range(1, 10)}
)
_ICON_MAX_BYTES: Final[int] = 8 * 1024 * 1024

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_VENDOR_DIR: Final[Path] = Path(__file__).resolve().parent / "vendor"
_SITE_PACKAGES: Final[Path] = Path(sysconfig.get_paths()["purelib"])
_DEV_EXTRA_DIRS: Final[tuple[str, ...]] = ("SoftwareIntro", "B1.0", "B_CHelper")
_DEV_EXTRA_FILES: Final[tuple[str, ...]] = ("requirements.txt", "README.md")

LogFn = Callable[[str], None]
PhaseFn = Callable[[str, str, int], None]


class BuildError(RuntimeError):
    """构建失败时抛出的可读异常。"""


class _FeaturePlan(NamedTuple):
    """单个功能在本次构建中的处理计划。"""

    spec: FeatureSpec
    included: bool
    dev: bool


def pyinstaller_version() -> str:
    """读取当前环境中的 PyInstaller 版本。

    Returns:
        版本号；未安装时返回空字符串。
    """
    try:
        return importlib.metadata.version("pyinstaller")
    except importlib.metadata.PackageNotFoundError:
        return ""


def python_embed_version() -> str:
    """返回与当前解释器一致的 python-embed 版本号。

    Returns:
        形如 ``3.15.2`` 的版本号。
    """
    info = sys.version_info
    return "%d.%d.%d" % (info.major, info.minor, info.micro)


def python_embed_url(version: str | None = None) -> str:
    """构造 64 位 python-embed 的阿里云下载地址。

    Args:
        version: 目标 Python 版本；``None`` 时使用当前解释器版本。

    Returns:
        下载 URL。
    """
    target: str = version or python_embed_version()
    return "%s/python-%s-embed-amd64.zip" % (PYTHON_EMBED_MIRROR, target)


def resolve_output_dir(value: str) -> Path:
    """解析构建输出目录。

    Args:
        value: 用户配置的目录；空字符串表示默认 ``/build/``。

    Returns:
        绝对输出目录。
    """
    if not value or not str(value).strip():
        return (_PROJECT_ROOT / "build").resolve()
    path: Path = Path(str(value).strip()).expanduser()
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    return path.resolve()


def safe_file_name(value: str) -> str:
    """把程序显示名称转换为 Windows 可用的文件名。

    允许中文与空格；替换 Windows 非法字符，处理保留名与首尾空白/点号。

    Args:
        value: 用户填写的程序名称。

    Returns:
        可用的文件名（不含扩展名）。
    """
    cleaned: str = _INVALID_FILENAME.sub("_", str(value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = cleaned[:80].strip(" .")
    if not cleaned:
        return APP_EXE_NAME
    if cleaned.upper() in _RESERVED_NAMES:
        cleaned = "_" + cleaned
    return cleaned


def build_package(
    version: str,
    dev_build: bool,
    output_dir: str,
    dev_format: str,
    dev_features: set[str],
    program_name: str = "",
    icon_data: str = "",
    icon_filename: str = "",
    *,
    log: LogFn,
    set_phase: PhaseFn,
) -> dict[str, Any]:
    """执行一次完整构建。

    Args:
        version: 导出显示版本号，必须符合 ``x.x.x``。
        dev_build: 是否为开发构建（全局导出）。
        output_dir: 用户配置的输出目录；空字符串使用 ``/build/``。
        dev_format: 开发构建格式，``"zip"`` 或 ``"executable"``。
        dev_features: 在设置中标记为 dev 的功能名称集合。
        program_name: 程序显示名称；空字符串使用默认名称。
        icon_data: 图标的 Base64 或 Data URL；空字符串表示不设置图标。
        icon_filename: 图标原始文件名，用于 .ico 兜底判断。
        log: 日志回调，接收单行文本。
        set_phase: 阶段回调，参数为 ``(phase, message, progress)``。

    Returns:
        构建结果字典，包含 ``kind``、``path``、``size``、``duration`` 等。

    Raises:
        BuildError: 参数非法、依赖缺失或构建失败时抛出。
    """
    if not VERSION_PATTERN.match(str(version or "")):
        raise BuildError("版本号不合法！请填写 x.x.x 或 x.x.x.x 形式（例如 2.1.3.7559）")
    if getattr(sys, "frozen", False):
        raise BuildError("已打包的应用不能再次构建，请从源码运行本程序")

    started: float = time.time()
    target_format: str = str(dev_format or "executable").strip().lower()
    if target_format not in {"zip", "executable"}:
        raise BuildError("开发构建格式必须是 zip 或 executable")
    display_name: str = str(program_name or "").strip() or APP_EXE_NAME
    exe_name: str = safe_file_name(display_name)

    plans: list[_FeaturePlan] = [
        _FeaturePlan(
            spec=spec,
            included=(
                dev_build
                or (spec.name != "构建" and spec.name not in dev_features)
            ),
            dev=spec.name in dev_features,
        )
        for spec in OFFICIAL_FEATURES
    ]
    included: list[FeatureSpec] = [plan.spec for plan in plans if plan.included]
    if not included:
        raise BuildError("没有可打包的功能，请检查 Feature 开发标记")

    output_root: Path = resolve_output_dir(output_dir)
    slug: str = "%s-v%s%s" % (
        exe_name,
        version,
        "-dev" if dev_build else "",
    )
    work_root: Path = output_root / ".work" / slug
    set_phase("prepare", "准备构建目录", 3)
    log("输出目录：%s" % output_root)
    log("程序名称：%s（可执行文件名：%s）" % (display_name, exe_name))
    log("导出版本：%s%s" % (version, "（开发构建）" if dev_build else "（发布构建）"))
    log("包含功能：%s" % "、".join(spec.name for spec in included))
    if not output_root.exists():
        output_root.mkdir(parents=True, exist_ok=True)
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)

    try:
        icon_path: Path | None = _prepare_icon(
            icon_data, icon_filename, work_root, log=log
        )
        if icon_path is not None:
            log("程序图标：%s" % icon_path)
        if dev_build and target_format == "zip":
            result: dict[str, Any] = _build_embedded_zip(
                version=version,
                slug=slug,
                output_root=output_root,
                work_root=work_root,
                included=included,
                display_name=display_name,
                exe_name=exe_name,
                icon_path=icon_path,
                log=log,
                set_phase=set_phase,
            )
        else:
            result = _build_executable(
                version=version,
                slug=slug,
                output_root=output_root,
                work_root=work_root,
                included=included,
                dev_build=dev_build,
                display_name=display_name,
                exe_name=exe_name,
                icon_path=icon_path,
                log=log,
                set_phase=set_phase,
            )
        result["duration"] = round(time.time() - started, 1)
        log("构建完成，用时 %.1f 秒。" % result["duration"])
        set_phase("done", "构建完成", 100)
    except Exception:
        # 失败时保留 .work 目录便于排查，并给出路径。
        log("构建失败，临时文件保留在：%s" % work_root)
        raise
    # 成功时清理临时目录，避免 build/.work 长期占用空间。
    shutil.rmtree(work_root, ignore_errors=True)
    return result


def _build_executable(
    version: str,
    slug: str,
    output_root: Path,
    work_root: Path,
    included: list[FeatureSpec],
    dev_build: bool,
    display_name: str,
    exe_name: str,
    icon_path: Path | None,
    log: LogFn,
    set_phase: PhaseFn,
) -> dict[str, Any]:
    """使用 PyInstaller 生成目录版可执行文件。

    Args:
        version: 导出显示版本号。
        slug: 产物目录名。
        output_root: 输出根目录。
        work_root: 本次构建的临时目录。
        included: 需要打包的功能。
        dev_build: 是否为开发构建。
        display_name: 程序显示名称。
        exe_name: 可执行文件名（不含扩展名）。
        icon_path: 转换后的 .ico 路径；``None`` 表示没有自定义图标。
        log: 日志回调。
        set_phase: 阶段回调。

    Returns:
        构建结果字典。
    """
    if not pyinstaller_version():
        raise BuildError(
            "未安装 PyInstaller，请先运行："
            "Scripts\\python.exe -m pip install pyinstaller "
            "-i https://pypi.tuna.tsinghua.edu.cn/simple"
        )

    stage: Path = work_root / "stage"
    set_phase("stage", "复制程序源码", 10)
    _copy_app_tree(stage, included, log=log)
    _write_build_info(
        stage / "hwklr" / "_build_info.py",
        version,
        dev_build,
        display_name,
        "icon.ico" if icon_path is not None else "",
    )
    log("源码已复制到临时目录。")

    dist_dir: Path = work_root / "dist"
    cmd: list[str] = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        exe_name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_root / "pyinstaller"),
        "--specpath",
        str(work_root / "spec"),
        "--paths",
        str(stage),
        "--add-data",
        _data_arg(stage / "hwklr" / "UI" / "page_data", "hwklr/UI/page_data"),
        "--add-data",
        _data_arg(
            stage / "hwklr" / "UI" / "tagview" / "view_data",
            "hwklr/UI/tagview/view_data",
        ),
        "--add-data",
        _data_arg(stage / "hwklr" / "runtime_data", "hwklr/runtime_data"),
    ]
    if icon_path is not None:
        # --icon 写入 exe 资源（资源管理器、任务栏、Alt+Tab）；
        # 同时把 ico 放到 _internal 供 pywebview 设置窗口图标。
        cmd.extend(["--icon", str(icon_path)])
        cmd.extend(["--add-data", _data_arg(icon_path, ".")])
    if sys.platform == "win32":
        version_file: Path = _write_version_file(
            work_root / "version_info.txt", version, display_name, exe_name
        )
        cmd.extend(["--version-file", str(version_file)])
    if dev_build:
        cmd.append("--console")
    else:
        # 发布构建：不显示终端，并启用字节码优化以减小体积、加快启动。
        cmd.extend(["--windowed", "--optimize", "2"])
        # 生产环境不会走到的模块：
        # - openpyxl / docx：仅用于 HSR 题库的多格式导入函数，当前 UI 无入口；
        # - setuptools / packaging：仅构建或 cffi 编译辅助使用，运行时不需要；
        # - lxml：C 页面解析已改用 bs4 自带的 html.parser，不再需要 lxml 二进制。
        for module in ("openpyxl", "docx", "setuptools", "packaging", "lxml"):
            cmd.extend(["--exclude-module", module])
    # PyInstaller 仅用于构建，不属于应用运行依赖；显式排除可避免将来误导入时进入产物。
    # 该选项只影响目标程序的依赖收集，不会影响当前正在执行的构建进程。
    cmd.extend(["--exclude-module", "PyInstaller"])
    # 可选功能通过动态导入加载，必须显式告诉 PyInstaller 收集。
    for spec in included:
        cmd.extend(["--hidden-import", spec.module])
    included_names: set[str] = {spec.name for spec in included}
    for spec in OFFICIAL_FEATURES:
        if spec.name not in included_names:
            cmd.extend(["--exclude-module", spec.module])
    cmd.append(str(stage / "main.py"))

    log("开始执行 PyInstaller：%s" % (" ".join(cmd)))
    set_phase("build", "PyInstaller 正在分析并打包", 20)
    env: dict[str, str] = dict(os.environ)
    env["PYTHONPATH"] = str(stage)
    creationflags: int = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    )
    proc: subprocess.Popen[str] = subprocess.Popen(
        cmd,
        cwd=str(stage),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line: str = raw_line.rstrip()
        if line:
            log(line)
    code: int = proc.wait()
    if code != 0:
        raise BuildError("PyInstaller 执行失败，退出码 %d" % code)

    built: Path = dist_dir / exe_name
    if not built.is_dir():
        raise BuildError("未找到 PyInstaller 输出目录: %s" % built)

    set_phase("package", "整理输出目录", 90)
    artifact: Path = output_root / slug
    _reset_artifact(artifact, output_root)
    shutil.copytree(built, artifact)
    if dev_build:
        _copy_dev_extras(artifact, log=log)
        _archive_sources(artifact, version, log=log)
    _write_manifest(
        artifact / "BUILD_INFO.json",
        version,
        dev_build,
        "executable",
        included,
        display_name,
        exe_name,
    )
    size: int = _tree_size(artifact)
    log("可执行文件：%s" % (artifact / (exe_name + ".exe")))
    log("产物大小：%.1f MB" % (size / 1024 / 1024))
    return {
        "kind": "directory",
        "path": str(artifact),
        "exe": str(artifact / (exe_name + ".exe")),
        "size": size,
        "name": display_name,
    }


def _build_embedded_zip(
    version: str,
    slug: str,
    output_root: Path,
    work_root: Path,
    included: list[FeatureSpec],
    display_name: str,
    exe_name: str,
    icon_path: Path | None,
    log: LogFn,
    set_phase: PhaseFn,
) -> dict[str, Any]:
    """生成使用 python-embed 运行时的 zip 开发包。

    Args:
        version: 导出显示版本号。
        slug: 产物目录名（同时作为 zip 内根目录名）。
        output_root: 输出根目录。
        work_root: 本次构建的临时目录。
        included: 需要打包的功能。
        display_name: 程序显示名称。
        exe_name: 程序文件名（zip 内用于标记）。
        icon_path: 转换后的 .ico 路径；``None`` 表示没有自定义图标。
        log: 日志回调。
        set_phase: 阶段回调。

    Returns:
        构建结果字典。
    """
    stage: Path = work_root / slug
    app_dir: Path = stage / "app"
    runtime_dir: Path = stage / "runtime"

    set_phase("stage", "复制程序源码", 8)
    _copy_app_tree(app_dir, included, log=log)
    _write_build_info(
        app_dir / "hwklr" / "_build_info.py",
        version,
        True,
        display_name,
        "icon.ico" if icon_path is not None else "",
    )
    if icon_path is not None:
        shutil.copy2(icon_path, app_dir / "icon.ico")
        shutil.copy2(icon_path, stage / "icon.ico")
    _copy_dev_extras(stage, log=log)
    _archive_sources(stage, version, log=log)

    set_phase("download", "准备 python-embed 运行时", 20)
    embed_zip: Path = _ensure_embed_zip(log=log)

    set_phase("stage", "解压 python-embed", 30)
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    runtime_dir.mkdir(parents=True)
    with zipfile.ZipFile(embed_zip) as archive:
        archive.extractall(runtime_dir)
    log("python-embed 已解压：%s" % runtime_dir)

    set_phase("stage", "复制第三方依赖", 35)
    target_site: Path = runtime_dir / "Lib" / "site-packages"
    if not _SITE_PACKAGES.is_dir():
        raise BuildError("未找到虚拟环境 site-packages: %s" % _SITE_PACKAGES)
    shutil.copytree(
        _SITE_PACKAGES,
        target_site,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    log("已复制依赖包：%s" % _SITE_PACKAGES)
    _rewrite_pth(runtime_dir)
    _write_start_bat(stage / "start.bat")
    _write_manifest(
        stage / "BUILD_INFO.json",
        version,
        True,
        "zip",
        included,
        display_name,
        exe_name,
    )

    set_phase("package", "压缩分发包", 55)
    archive_path: Path = output_root / (slug + ".zip")
    if archive_path.exists():
        archive_path.unlink()
    _zip_directory(stage, archive_path, log=log, set_phase=set_phase)

    size: int = archive_path.stat().st_size
    log("zip 分发包：%s" % archive_path)
    log("产物大小：%.1f MB" % (size / 1024 / 1024))
    return {
        "kind": "zip",
        "path": str(archive_path),
        "exe": "",
        "size": size,
        "name": display_name,
    }


def _copy_app_tree(dest: Path, included: list[FeatureSpec], *, log: LogFn) -> None:
    """把运行所需源码复制到临时目录，并按功能清单裁剪。

    Args:
        dest: 目标根目录。
        included: 需要保留的功能。
        log: 日志回调。
    """
    dest.mkdir(parents=True, exist_ok=True)
    main_src: Path = _PROJECT_ROOT / "main.py"
    if not main_src.is_file():
        raise BuildError("未找到入口文件: %s" % main_src)
    shutil.copy2(main_src, dest / "main.py")

    included_names: set[str] = {spec.name for spec in included}
    excluded_prefixes: list[str] = []
    # 形如 hsr_bank_v1.0.json 的知识库按模块包名归属到对应功能。
    excluded_file_prefixes: list[str] = []
    for spec in OFFICIAL_FEATURES:
        if spec.name in included_names:
            continue
        package_name: str = spec.module.rsplit(".", 1)[-1]
        excluded_prefixes.append("hwklr/features/%s" % package_name)
        excluded_prefixes.append(
            "hwklr/UI/tagview/view_data/%s" % spec.view_dir
        )
        excluded_file_prefixes.append(
            "hwklr/runtime_data/%s_bank_" % package_name
        )
    # vendor 中是按需下载的 python-embed 缓存，不进入导出包。
    excluded_prefixes.append("hwklr/features/build/vendor")

    def ignore(directory: str, names: list[str]) -> set[str]:
        """返回需要忽略的文件/目录名。

        Args:
            directory: 当前目录。
            names: 目录中的名称。

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
                continue
            if any(
                relative == prefix or relative.startswith(prefix + "/")
                for prefix in excluded_prefixes
            ):
                ignored.add(name)
                continue
            if any(relative.startswith(prefix) for prefix in excluded_file_prefixes):
                ignored.add(name)
        return ignored

    shutil.copytree(_PROJECT_ROOT / "hwklr", dest / "hwklr", ignore=ignore)
    log("已按功能清单裁剪源码（保留 %d 个功能）。" % len(included))


def _write_build_info(
    path: Path,
    version: str,
    dev_build: bool,
    display_name: str,
    icon_path: str = "",
) -> None:
    """写入导出构建的版本、名称、图标与开发标记。

    Args:
        path: ``_build_info.py`` 目标路径。
        version: 导出显示版本号。
        dev_build: 是否为开发构建。
        display_name: 程序显示名称。
        icon_path: 相对程序根目录的 ico 路径；空字符串表示没有图标。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # 默认名称留空，让程序沿用内置标题（含“· 作业助手”），只有自定义名称才覆盖。
    export_name: str = "" if display_name == APP_EXE_NAME else display_name
    path.write_text(
        "# -*- coding: utf-8 -*-\n"
        "# 由 hwklr 构建功能自动生成，请勿手动修改。\n"
        "__version__ = %r\n"
        "EXPORT_VERSION = %r\n"
        "EXPORT_NAME = %r\n"
        "DEV_BUILD = %r\n"
        "ICON_PATH = %r\n"
        % (__version__, version, export_name, bool(dev_build), icon_path),
        encoding="utf-8",
    )


def _write_manifest(
    path: Path,
    version: str,
    dev_build: bool,
    build_format: str,
    included: list[FeatureSpec],
    display_name: str,
    exe_name: str,
) -> None:
    """在产物根目录写入构建信息。

    Args:
        path: 目标文件路径。
        version: 导出显示版本号。
        dev_build: 是否为开发构建。
        build_format: ``executable`` 或 ``zip``。
        included: 包含的功能。
        display_name: 程序显示名称。
        exe_name: 可执行文件名（不含扩展名）。
    """
    data: dict[str, Any] = {
        "app": display_name,
        "exe_name": exe_name,
        "version": version,
        "dev_build": bool(dev_build),
        "format": build_format,
        "features": [spec.name for spec in included],
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _prepare_icon(
    icon_data: str,
    icon_filename: str,
    work_root: Path,
    *,
    log: LogFn,
) -> Path | None:
    """解码用户选择的图片并生成多尺寸 .ico。

    Args:
        icon_data: Base64 或 Data URL。
        icon_filename: 原始文件名。
        work_root: 本次构建临时目录。
        log: 日志回调。

    Returns:
        生成的 ico 路径；没有提供图标时返回 ``None``。

    Raises:
        BuildError: 数据无法解码、文件过大或无法转换为图标时抛出。
    """
    payload: str = str(icon_data or "").strip()
    if not payload:
        return None
    if payload.startswith("data:") and "," in payload:
        payload = payload.split(",", 1)[1]
    try:
        raw: bytes = base64.b64decode(payload, validate=False)
    except (ValueError, TypeError) as exc:
        raise BuildError("图标数据无法解析：%s" % exc) from exc
    if not raw:
        raise BuildError("图标文件为空")
    if len(raw) > _ICON_MAX_BYTES:
        raise BuildError("图标文件过大（最大 8 MB）")

    target: Path = work_root / "icon.ico"
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            rgba: Any = image.convert("RGBA")
            longest: int = max(rgba.size)
            sizes: list[tuple[int, int]] = [
                (side, side)
                for side in (16, 24, 32, 48, 64, 128, 256)
                if side <= longest
            ]
            if not sizes:
                side = max(1, min(longest, 16))
                sizes = [(side, side)]
            rgba.save(target, format="ICO", sizes=sizes)
    except BuildError:
        raise
    except Exception as exc:
        # 已经是合法 ico 时直接使用原始字节，避免重新编码失败。
        if str(icon_filename or "").lower().endswith(".ico"):
            target.write_bytes(raw)
        else:
            raise BuildError("无法读取图标文件：%s" % exc) from exc
    log("图标已转换为 ico（%d 字节）。" % target.stat().st_size)
    return target


def _write_version_file(
    path: Path,
    version: str,
    display_name: str,
    exe_name: str,
) -> Path:
    """生成 PyInstaller Windows 版本资源文件。

    Args:
        path: 输出的 ``version_info.txt`` 路径。
        version: 导出显示版本号 ``x.x.x`` 或 ``x.x.x.x``。
        display_name: 程序显示名称。
        exe_name: 可执行文件名。

    Returns:
        版本资源文件路径。
    """
    parts: list[int] = [int(item) for item in version.split(".")]
    if len(parts) < 3:
        raise BuildError("版本号至少需要三段")
    if any(part < 0 or part > 65535 for part in parts):
        raise BuildError("版本号每段必须在 0~65535 之间")
    major, minor, patch = parts[0], parts[1], parts[2]
    build: int = parts[3] if len(parts) >= 4 else 0
    content: str = (
        "# 由 hwklr 构建功能自动生成。\n"
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        "    filevers=(%d, %d, %d, %d),\n"
        "    prodvers=(%d, %d, %d, %d),\n"
        "    mask=0x3f,\n"
        "    flags=0x0,\n"
        "    OS=0x40004,\n"
        "    fileType=0x1,\n"
        "    subtype=0x0,\n"
        "    date=(0, 0)\n"
        "  ),\n"
        "  kids=[\n"
        "    StringFileInfo([\n"
        "      StringTable('080404B0', [\n"
        "        StringStruct('CompanyName', 'Gary'),\n"
        "        StringStruct('FileDescription', %r),\n"
        "        StringStruct('FileVersion', %r),\n"
        "        StringStruct('InternalName', %r),\n"
        "        StringStruct('OriginalFilename', %r),\n"
        "        StringStruct('ProductName', %r),\n"
        "        StringStruct('ProductVersion', %r)\n"
        "      ])\n"
        "    ]),\n"
        "    VarFileInfo([VarStruct('Translation', [2052, 1200])])\n"
        "  ]\n"
        ")\n"
        % (
            major,
            minor,
            patch,
            build,
            major,
            minor,
            patch,
            build,
            display_name,
            version,
            exe_name,
            exe_name + ".exe",
            display_name,
            version,
        )
    )
    path.write_text(content, encoding="utf-8")
    return path


def _archive_sources(dest: Path, version: str, *, log: LogFn) -> Path:
    """把当前源代码（不含测试）与 requirements.txt 归档到产物目录。

    Args:
        dest: 产物根目录。
        version: 导出显示版本号。
        log: 日志回调。

    Returns:
        生成的源码 zip 路径。
    """
    archive_path: Path = dest / ("source-v%s.zip" % version)
    included: list[Path] = []
    main_file: Path = _PROJECT_ROOT / "main.py"
    requirements: Path = _PROJECT_ROOT / "requirements.txt"
    for file_path in (main_file, requirements):
        if file_path.is_file():
            included.append(file_path)
    for file_path in (_PROJECT_ROOT / "hwklr").rglob("*"):
        if not file_path.is_file():
            continue
        relative: Path = file_path.relative_to(_PROJECT_ROOT)
        parts: tuple[str, ...] = relative.parts
        if "__pycache__" in parts:
            continue
        if file_path.suffix in {".pyc", ".pyo"}:
            continue
        if "tests" in parts or "test" in parts:
            continue
        if file_path.name.startswith("test_") or file_path.name.endswith("_test.py"):
            continue
        if relative.as_posix().startswith("hwklr/features/build/vendor/"):
            continue
        included.append(file_path)

    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for file_path in included:
            archive.write(
                file_path,
                arcname=file_path.relative_to(_PROJECT_ROOT).as_posix(),
            )
    log(
        "源码归档：%s（%d 个文件，%.1f MB）"
        % (
            archive_path.name,
            len(included),
            archive_path.stat().st_size / 1024 / 1024,
        )
    )
    return archive_path


def _ensure_embed_zip(*, log: LogFn) -> Path:
    """确保 python-embed 压缩包已下载到构建功能目录。

    Args:
        log: 日志回调。

    Returns:
        本地 zip 路径。

    Raises:
        BuildError: 下载失败或压缩包损坏时抛出。
    """
    version: str = python_embed_version()
    name: str = "python-%s-embed-amd64.zip" % version
    target: Path = _VENDOR_DIR / name
    if target.is_file() and target.stat().st_size > 1024 * 1024:
        log("使用已缓存的 python-embed：%s" % target)
        return target

    _VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    url: str = python_embed_url(version)
    log("正在从阿里云镜像下载 python-embed：%s" % url)
    part: Path = target.with_suffix(".zip.part")
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "HomeworkKiller4BJTU-Builder/2.1.0"}
        )
        with urllib.request.urlopen(request, timeout=60) as response, part.open(
            "wb"
        ) as output:
            total: int = int(response.headers.get("Content-Length") or 0)
            downloaded: int = 0
            while True:
                chunk: bytes = response.read(1024 * 256)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                if total:
                    log(
                        "下载进度：%.1f%%（%.1f MB / %.1f MB）"
                        % (
                            downloaded * 100.0 / total,
                            downloaded / 1024 / 1024,
                            total / 1024 / 1024,
                        )
                    )
        part.replace(target)
    except (OSError, urllib.error.URLError) as exc:
        part.unlink(missing_ok=True)
        raise BuildError("下载 python-embed 失败: %s" % exc) from exc

    try:
        with zipfile.ZipFile(target) as archive:
            bad: str | None = archive.testzip()
            if bad:
                raise BuildError("python-embed 压缩包校验失败: %s" % bad)
    except zipfile.BadZipFile as exc:
        target.unlink(missing_ok=True)
        raise BuildError("python-embed 压缩包损坏: %s" % exc) from exc
    log("python-embed 已保存到：%s" % target)
    return target


def _rewrite_pth(runtime_dir: Path) -> None:
    """重写 python-embed 的 ``._pth``，加入依赖与 app 目录。

    Args:
        runtime_dir: python-embed 解压目录。
    """
    info = sys.version_info
    zip_name: str = "python%d%d.zip" % (info.major, info.minor)
    candidates: list[Path] = sorted(runtime_dir.glob("python*._pth"))
    target: Path = (
        candidates[0] if candidates else runtime_dir / ("python%d%d._pth" % (info.major, info.minor))
    )
    lines: list[str] = [
        zip_name,
        ".",
        "Lib\\site-packages",
        "..\\app",
        "import site",
    ]
    target.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")


def _write_start_bat(path: Path) -> None:
    """写入 ASCII-only 的启动批处理（避免中文 Windows 编码问题）。

    Args:
        path: ``start.bat`` 路径。
    """
    content: str = (
        "@echo off\r\n"
        "setlocal\r\n"
        "cd /d \"%~dp0\"\r\n"
        "\"%~dp0runtime\\python.exe\" \"%~dp0app\\main.py\"\r\n"
        "echo.\r\n"
        "echo Application exited.\r\n"
        "pause\r\n"
    )
    path.write_text(content, encoding="ascii")


def _zip_directory(
    directory: Path,
    archive_path: Path,
    *,
    log: LogFn,
    set_phase: PhaseFn,
) -> None:
    """把目录压缩为 zip，根目录使用目录名。

    Args:
        directory: 待压缩目录（名称即 zip 内根目录名）。
        archive_path: 输出 zip 路径。
        log: 日志回调。
        set_phase: 阶段回调。
    """
    files: list[Path] = [path for path in directory.rglob("*") if path.is_file()]
    total: int = len(files)
    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for index, file_path in enumerate(files, start=1):
            relative: Path = file_path.relative_to(directory)
            archive.write(file_path, arcname=str(Path(directory.name) / relative))
            if index % 200 == 0 or index == total:
                progress: int = 55 + int(index * 40 / max(total, 1))
                set_phase(
                    "package",
                    "压缩分发包 %d/%d" % (index, total),
                    min(progress, 95),
                )
                log("压缩中：%d/%d" % (index, total))


def _copy_dev_extras(dest: Path, *, log: LogFn) -> None:
    """开发构建附带参考文档与原型目录。

    Args:
        dest: 产物根目录。
        log: 日志回调。
    """
    for name in _DEV_EXTRA_DIRS:
        source: Path = _PROJECT_ROOT / name
        if source.is_dir():
            target: Path = dest / name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
            log("附带开发资料：%s" % name)
    for name in _DEV_EXTRA_FILES:
        source = _PROJECT_ROOT / name
        if source.is_file():
            shutil.copy2(source, dest / name)


def _reset_artifact(artifact: Path, output_root: Path) -> None:
    """删除旧的同名产物，避免新旧文件混杂。

    Args:
        artifact: 产物目录。
        output_root: 输出根目录；仅允许删除其直接子目录。
    """
    if not artifact.exists():
        return
    if artifact.resolve().parent != output_root.resolve():
        raise BuildError("拒绝删除输出目录之外的路径: %s" % artifact)
    shutil.rmtree(artifact)


def _data_arg(source: Path, destination: str) -> str:
    """构造 PyInstaller ``--add-data`` 参数。

    Args:
        source: 本地源目录。
        destination: 包内目标目录。

    Returns:
        ``source<pathsep>destination`` 形式字符串。
    """
    return "%s%s%s" % (source, os.pathsep, destination)


def _tree_size(root: Path) -> int:
    """统计目录总字节数。

    Args:
        root: 目录路径。

    Returns:
        总字节数。
    """
    total: int = 0
    for path in root.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total
