# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 最后更新: 2026-11-12 13:00
# 文件名: server.py
# 主要用途: 提供本地静态资源 / API 服务，支持官方 view_data、第三方扩展资源与欢迎弹窗数据。
# 文件版本: 4.6.1
"""本地 UI 服务。

pywebview 通过 ``http://127.0.0.1:<port>/`` 加载页面。使用自有 HTTP 服务
而不是 pywebview 内置服务，便于固定起始端口、同时暴露 page_data /
view_data 两个资源根目录，并提供 ``/api/tags``、``/api/meta`` 与
``/api/welcome`` 接口。
"""
from __future__ import annotations

import json
import logging
import mimetypes
import sys
import threading
import urllib.parse
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final

__version__ = "4.6.1"
__all__ = ["UiHttpServer"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_DEFAULT_PORT: Final[int] = 49152
_PORT_SCAN_LIMIT: Final[int] = 100


class _UiHttpServer(ThreadingHTTPServer):
    """支持线程处理的本地服务器。

    注意：Windows 下 ``SO_REUSEADDR`` 允许重复绑定同一端口，会导致“端口被占用”
    检测失效，因此这里显式关闭地址复用，确保端口占用时能顺延到下一个端口。
    """

    daemon_threads: bool = True
    # Windows 的 SO_REUSEADDR 会允许重复绑定已占用端口，故在 Windows 关闭；
    # 类 Unix 系统允许复用处于 TIME_WAIT 的端口，便于快速重启。
    allow_reuse_address: bool = sys.platform != "win32"
    allow_reuse_port: bool = False
    extension_resolver: Callable[[str], Path | None]


class _UiRequestHandler(BaseHTTPRequestHandler):
    """处理静态资源与轻量 API 请求。"""

    server_version: str = "HomeworkKillerUI/1.0"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定命名
        """处理 GET 请求。"""
        self._handle_request(send_body=True)

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定命名
        """处理 HEAD 请求。"""
        self._handle_request(send_body=False)

    def log_message(self, format: str, *args: Any) -> None:
        """屏蔽默认访问日志，避免污染控制台。

        Args:
            format: 日志格式串。
            *args: 格式参数。
        """
        _LOGGER.debug("UI HTTP: " + format, *args)

    def _handle_request(self, send_body: bool) -> None:
        """解析路径并输出对应内容。

        Args:
            send_body: 是否发送响应体（HEAD 请求为 ``False``）。
        """
        parsed: urllib.parse.ParseResult = urllib.parse.urlparse(self.path)
        request_path: str = urllib.parse.unquote(parsed.path)
        server: _UiHttpServer = self.server  # type: ignore[assignment]

        if request_path == "/":
            self._send_file(server.page_dir / "index.html", send_body)
            return
        if request_path == "/api/health":
            self._send_json({"ok": True}, send_body)
            return
        if request_path == "/api/tags":
            provider: Callable[[], list[dict[str, Any]]] = server.tags_provider
            self._send_json(provider(), send_body)
            return
        if request_path == "/api/meta":
            meta_provider: Callable[[], dict[str, Any]] = server.meta_provider
            self._send_json(meta_provider(), send_body)
            return
        if request_path == "/api/welcome":
            welcome_provider: Callable[[], dict[str, Any]] = server.welcome_provider
            self._send_json(welcome_provider(), send_body)
            return
        if request_path == "/favicon.ico":
            self._send_status(204, send_body)
            return
        if request_path.startswith("/page_data/"):
            relative: str = request_path[len("/page_data/"):]
            self._send_file(server.page_dir / relative, send_body)
            return
        if request_path.startswith("/view_data/"):
            relative = request_path[len("/view_data/"):]
            self._send_file(server.view_data_dir / relative, send_body)
            return
        if request_path.startswith("/extensions/"):
            relative = request_path[len("/extensions/"):]
            parts: list[str] = relative.split("/", 1)
            extension_id: str = parts[0] if parts else ""
            rest: str = parts[1] if len(parts) > 1 else ""
            if not extension_id or not rest:
                self._send_status(404, send_body)
                return
            resolver: Callable[[str], Path | None] = server.extension_resolver
            extension_root: Path | None = resolver(extension_id)
            if extension_root is None:
                self._send_status(404, send_body)
                return
            self._send_file(
                extension_root / rest,
                send_body,
                root=extension_root,
            )
            return
        self._send_status(404, send_body)

    def _send_file(
        self,
        path: Path,
        send_body: bool,
        root: Path | None = None,
    ) -> None:
        """安全地发送静态文件。

        Args:
            path: 目标文件路径。
            send_body: 是否发送响应体。
            root: 允许访问的根目录；``None`` 时按官方资源目录推断。
        """
        server: _UiHttpServer = self.server  # type: ignore[assignment]
        if root is None:
            root = (
                server.view_data_dir
                if server.view_data_dir in path.parents
                else server.page_dir
            )
        resolved_root: Path = root.resolve()
        try:
            resolved_path: Path = path.resolve()
            resolved_path.relative_to(resolved_root)
        except (OSError, ValueError):
            self._send_status(403, send_body)
            return
        if not resolved_path.is_file():
            self._send_status(404, send_body)
            return

        content_type: str = _content_type(resolved_path)
        try:
            data: bytes = resolved_path.read_bytes()
        except OSError as exc:
            _LOGGER.warning("读取静态资源失败 %s: %s", resolved_path, exc)
            self._send_status(500, send_body)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if send_body:
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _send_json(self, payload: Any, send_body: bool) -> None:
        """发送 JSON 响应。

        Args:
            payload: 可 JSON 序列化的对象。
            send_body: 是否发送响应体。
        """
        data: bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if send_body:
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _send_status(self, status: int, send_body: bool) -> None:
        """发送无内容的状态响应。

        Args:
            status: HTTP 状态码。
            send_body: 是否发送响应体。
        """
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()


def _content_type(path: Path) -> str:
    """根据扩展名返回 Content-Type。

    Args:
        path: 文件路径。

    Returns:
        MIME 类型字符串。
    """
    overrides: Final[dict[str, str]] = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
    }
    suffix: str = path.suffix.lower()
    if suffix in overrides:
        return overrides[suffix]
    guessed: str | None = mimetypes.guess_type(str(path))[0]
    return guessed or "application/octet-stream"


class UiHttpServer:
    """本地 UI HTTP 服务封装。"""

    def __init__(
        self,
        page_dir: Path,
        view_data_dir: Path,
        preferred_port: int = _DEFAULT_PORT,
        tags_provider: Callable[[], list[dict[str, Any]]] | None = None,
        meta_provider: Callable[[], dict[str, Any]] | None = None,
        welcome_provider: Callable[[], dict[str, Any]] | None = None,
        extension_resolver: Callable[[str], Path | None] | None = None,
    ) -> None:
        """初始化服务。

        Args:
            page_dir: 公共 UI 资源目录（page_data）。
            view_data_dir: 标签资源目录（view_data）。
            preferred_port: 首选端口，默认 49152。
            tags_provider: 返回标签列表的回调。
            meta_provider: 返回应用元信息的回调。
            welcome_provider: 返回欢迎弹窗数据的回调。
            extension_resolver: 按扩展 ID 返回资源根目录的回调。
        """
        self._page_dir: Path = page_dir
        self._view_data_dir: Path = view_data_dir
        self._preferred_port: int = (
            preferred_port if 1 <= preferred_port <= 65535 else _DEFAULT_PORT
        )
        self._tags_provider: Callable[[], list[dict[str, Any]]] = tags_provider or (lambda: [])
        self._meta_provider: Callable[[], dict[str, Any]] = meta_provider or (lambda: {})
        self._welcome_provider: Callable[[], dict[str, Any]] = (
            welcome_provider or (lambda: {"show": False})
        )
        self._extension_resolver: Callable[[str], Path | None] = (
            extension_resolver or (lambda extension_id: None)
        )
        self._httpd: _UiHttpServer | None = None
        self._thread: threading.Thread | None = None
        self._port: int = 0

    @property
    def port(self) -> int:
        """返回实际监听端口。

        Returns:
            端口号；未启动时为 ``0``。
        """
        return self._port

    def start(self) -> int:
        """启动服务，自动处理端口占用。

        Returns:
            实际监听端口。

        Raises:
            OSError: 连续 100 个端口都不可用时抛出。
        """
        last_error: OSError | None = None
        for offset in range(_PORT_SCAN_LIMIT):
            port: int = self._preferred_port + offset
            if port > 65535:
                break
            try:
                httpd: _UiHttpServer = _UiHttpServer(("127.0.0.1", port), _UiRequestHandler)
            except OSError as exc:
                last_error = exc
                continue
            # 通过服务器实例携带资源目录与回调，供请求处理器读取。
            httpd.page_dir = self._page_dir  # type: ignore[attr-defined]
            httpd.view_data_dir = self._view_data_dir  # type: ignore[attr-defined]
            httpd.tags_provider = self._tags_provider  # type: ignore[attr-defined]
            httpd.meta_provider = self._meta_provider  # type: ignore[attr-defined]
            httpd.welcome_provider = self._welcome_provider  # type: ignore[attr-defined]
            httpd.extension_resolver = self._extension_resolver  # type: ignore[attr-defined]
            self._httpd = httpd
            self._port = port
            self._thread = threading.Thread(
                target=httpd.serve_forever, name="UiHttpServer", daemon=True
            )
            self._thread.start()
            _LOGGER.info("UI 服务已启动: http://127.0.0.1:%d/", port)
            return port
        raise OSError(
            "无法在 %d 之后找到空闲端口" % self._preferred_port
        ) from last_error

    def stop(self) -> None:
        """停止服务并释放端口。"""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._port = 0
