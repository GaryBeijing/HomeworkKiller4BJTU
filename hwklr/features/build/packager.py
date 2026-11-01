# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-01 12:40
# 文件名: packager.py
# 主要用途: 构建功能的打包实现：源码裁剪、PyInstaller 目录版/可执行文件、python-embed zip 与版本注入。
# 文件版本: 2.1.0
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

import importlib.metadata
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

__version__ = "2.1.0"
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
]

APP_EXE_NAME: Final[str] = "HomeworkKiller4BJTU"
PYTHON_EMBED_MIRROR: Final[str] = (
    "https://mirrors.aliyun.com/python-release/windows"
)
VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\d+\.\d+\.\d+$")

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


def build_package(
    version: str,
    dev_build: bool,
    output_dir: str,
    dev_format: str,
    dev_features: set[str],
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
        log: 日志回调，接收单行文本。
        set_phase: 阶段回调，参数为 ``(phase, message, progress)``。

    Returns:
        构建结果字典，包含 ``kind``、``path``、``size``、``duration`` 等。

    Raises:
        BuildError: 参数非法、依赖缺失或构建失败时抛出。
    """
    if not VERSION_PATTERN.match(str(version or "")):
        raise BuildError("版本号不合法！请填写 x.x.x 形式（例如 2.1.0）")
    if getattr(sys, "frozen", False):
        raise BuildError("已打包的应用不能再次构建，请从源码运行本程序")

    started: float = time.time()
    target_format: str = str(dev_format or "executable").strip().lower()
    if target_format not in {"zip", "executable"}:
        raise BuildError("开发构建格式必须是 zip 或 executable")

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
    slug: str = "%s-v%s%s" % (APP_EXE_NAME, version, "-dev" if dev_build else "")
    work_root: Path = output_root / ".work" / slug
    set_phase("prepare", "准备构建目录", 3)
    log("输出目录：%s" % output_root)
    log("导出版本：%s%s" % (version, "（开发构建）" if dev_build else "（发布构建）"))
    log("包含功能：%s" % "、".join(spec.name for spec in included))
    if not output_root.exists():
        output_root.mkdir(parents=True, exist_ok=True)
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)

    try:
        if dev_build and target_format == "zip":
            result: dict[str, Any] = _build_embedded_zip(
                version=version,
                slug=slug,
                output_root=output_root,
                work_root=work_root,
                included=included,
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
    _write_build_info(stage / "hwklr" / "_build_info.py", version, dev_build)
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
        APP_EXE_NAME,
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
    if dev_build:
        cmd.append("--console")
    else:
        # 发布构建：不显示终端，并启用字节码优化以减小体积、加快启动。
        cmd.extend(["--windowed", "--optimize", "2"])
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

    built: Path = dist_dir / APP_EXE_NAME
    if not built.is_dir():
        raise BuildError("未找到 PyInstaller 输出目录: %s" % built)

    set_phase("package", "整理输出目录", 90)
    artifact: Path = output_root / slug
    _reset_artifact(artifact, output_root)
    shutil.copytree(built, artifact)
    if dev_build:
        _copy_dev_extras(artifact, log=log)
    _write_manifest(artifact / "BUILD_INFO.json", version, dev_build, "executable", included)
    size: int = _tree_size(artifact)
    log("可执行文件：%s" % (artifact / (APP_EXE_NAME + ".exe")))
    log("产物大小：%.1f MB" % (size / 1024 / 1024))
    return {
        "kind": "directory",
        "path": str(artifact),
        "exe": str(artifact / (APP_EXE_NAME + ".exe")),
        "size": size,
    }


def _build_embedded_zip(
    version: str,
    slug: str,
    output_root: Path,
    work_root: Path,
    included: list[FeatureSpec],
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
    _write_build_info(app_dir / "hwklr" / "_build_info.py", version, True)
    _copy_dev_extras(stage, log=log)

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
    _write_manifest(stage / "BUILD_INFO.json", version, True, "zip", included)

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


def _write_build_info(path: Path, version: str, dev_build: bool) -> None:
    """写入导出构建的版本覆盖模块。

    Args:
        path: ``_build_info.py`` 目标路径。
        version: 导出显示版本号。
        dev_build: 是否为开发构建。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# -*- coding: utf-8 -*-\n"
        "# 由 hwklr 构建功能自动生成，请勿手动修改。\n"
        "__version__ = \"2.1.0\"\n"
        "EXPORT_VERSION = %r\n"
        "DEV_BUILD = %r\n" % (version, bool(dev_build)),
        encoding="utf-8",
    )


def _write_manifest(
    path: Path,
    version: str,
    dev_build: bool,
    build_format: str,
    included: list[FeatureSpec],
) -> None:
    """在产物根目录写入构建信息。

    Args:
        path: 目标文件路径。
        version: 导出显示版本号。
        dev_build: 是否为开发构建。
        build_format: ``executable`` 或 ``zip``。
        included: 包含的功能。
    """
    data: dict[str, Any] = {
        "app": APP_EXE_NAME,
        "version": version,
        "dev_build": bool(dev_build),
        "format": build_format,
        "features": [spec.name for spec in included],
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


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
