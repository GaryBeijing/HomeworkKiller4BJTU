# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: browser_session.py
# 主要用途: Playwright 浏览器会话：附着 CDP 或无头启动系统 Edge。
# 文件版本: 4.0.0
"""Playwright 浏览器会话。

两种模式：
1. 附着到 ``tools/start-edge-debug.ps1`` 启动的 Edge（默认，复用登录态）；
2. 无头启动系统 Edge + ``storage_state``（静默模式，不抢占 profile 锁）。

注意：附着模式下 ``close()`` 只断开 Playwright，不关闭用户的 Edge。
"""

from __future__ import annotations

import json
import time
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from .config import storage_state_file
from .paths import artifacts_dir

DEFAULT_CDP_URL = "http://127.0.0.1:9222"


class BrowserSessionError(Exception):
    """浏览器连接/启动失败。"""


def default_storage_state() -> Path:
    """返回无头模式使用的 storage_state 文件。"""
    return storage_state_file()


def cdp_alive(port: int = 9222, timeout: float = 1.5) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version", timeout=timeout
        ) as response:
            data = json.load(response)
    except Exception:
        return False
    return "webSocketDebuggerUrl" in data


class BrowserSession(AbstractContextManager["BrowserSession"]):
    def __init__(
        self,
        *,
        port: int = 9222,
        headless: bool = False,
        attach: bool = True,
        storage_state: Path | str | None = None,
        channel: str = "msedge",
        default_timeout_ms: int = 30_000,
    ) -> None:
        self.port = port
        self.headless = headless
        self.attach = attach
        self.storage_state = Path(storage_state) if storage_state else None
        self.channel = channel
        self.default_timeout_ms = default_timeout_ms

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._owned = False
        self._closed = False

    # ------------------------------------------------------------------ 生命周期
    def __enter__(self) -> "BrowserSession":
        self._playwright = sync_playwright().start()
        if not self.attach and not self.headless:
            self._shutdown_playwright()
            raise BrowserSessionError("attach=False 只能用于无头模式")
        if self.attach:
            try:
                self._browser = self._playwright.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{self.port}"
                )
                contexts = self._browser.contexts
                if not contexts:
                    raise BrowserSessionError("调试浏览器没有可用的 context")
                self._context = contexts[0]
                self._context.set_default_timeout(self.default_timeout_ms)
                self._context.set_default_navigation_timeout(90_000)
                return self
            except Exception as exc:
                if not self.headless:
                    self._shutdown_playwright()
                    raise BrowserSessionError(
                        "无法连接浏览器调试端口 9222。请先运行：\n"
                        "  powershell -NoProfile -ExecutionPolicy Bypass "
                        "-File tools\\start-edge-debug.ps1"
                    ) from exc

        # 静默模式：系统 Edge + storage_state
        state = self.storage_state or default_storage_state()
        if not Path(state).is_file():
            self._shutdown_playwright()
            raise BrowserSessionError(
                f"静默模式需要登录态文件：{state}\n"
                "请先在慕课页面完成登录，或导入 Cookie 后重试。"
            )
        args = [
            "--autoplay-policy=no-user-gesture-required",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            "--mute-audio",
            "--no-first-run",
        ]
        try:
            self._browser = self._playwright.chromium.launch(
                channel=self.channel, headless=True, args=args
            )
            self._context = self._browser.new_context(storage_state=str(state))
            self._context.set_default_timeout(self.default_timeout_ms)
            self._context.set_default_navigation_timeout(90_000)
            self._owned = True
            return self
        except Exception as exc:
            self._shutdown_playwright()
            raise BrowserSessionError(f"无头 Edge 启动失败：{exc}") from exc

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # 附着模式只断开；自有浏览器才真正关闭。
        if self._owned and self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
        self._browser = None
        self._context = None
        self._shutdown_playwright()

    def _shutdown_playwright(self) -> None:
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    # ------------------------------------------------------------------ 访问
    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise BrowserSessionError("浏览器会话尚未启动")
        return self._context

    @property
    def browser(self) -> Browser:
        if self._browser is None:
            raise BrowserSessionError("浏览器会话尚未启动")
        return self._browser

    @property
    def owned(self) -> bool:
        return self._owned

    def find_page(self, url_part: str | None = None) -> Page | None:
        pages = self.context.pages
        if not pages:
            return None
        if not url_part:
            return pages[0]
        for page in pages:
            if url_part in page.url:
                return page
        return None

    def page(self, url_part: str | None = None, *, create: bool = True) -> Page:
        found = self.find_page(url_part)
        if found is not None:
            return found
        if not create:
            raise BrowserSessionError(f"没有找到包含 {url_part!r} 的页面")
        return self.context.new_page()

    def open(self, url: str, *, page: Page | None = None, timeout: int = 90_000) -> Page:
        target = page or self.page()
        # SPA 对「仅 hash 变化」的 goto 不一定重新渲染；先到 about:blank 强制整页加载。
        if "#" in url:
            try:
                target.goto("about:blank", wait_until="domcontentloaded", timeout=10_000)
            except Exception:
                pass
        target.goto(url, wait_until="domcontentloaded", timeout=timeout)
        return target

    def new_page(self, url: str | None = None) -> Page:
        page = self.context.new_page()
        if url:
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        return page

    def export_storage_state(self, path: Path | str | None = None) -> Path:
        target = Path(path) if path else default_storage_state()
        target.parent.mkdir(parents=True, exist_ok=True)
        self.context.storage_state(path=str(target))
        return target

    def screenshot(
        self,
        page: Page,
        path: Path | str | None = None,
        *,
        full_page: bool = False,
    ) -> Path:
        if path:
            target = Path(path)
            if not target.is_absolute():
                name = str(target).replace("\\", "/")
                if name.startswith(".artifacts/"):
                    name = name[len(".artifacts/"):]
                target = artifacts_dir() / name
        else:
            target = artifacts_dir() / f"shot-{int(time.time())}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(
                path=str(target),
                full_page=full_page,
                animations="disabled",
                timeout=15_000,
            )
            return target
        except PlaywrightTimeoutError:
            # 视频页偶尔卡在字体/动画；退回 CDP 直接截图。
            cdp = self.context.new_cdp_session(page)
            try:
                result = cdp.send("Page.captureScreenshot", {"format": "png"})
                import base64

                target.write_bytes(base64.b64decode(result["data"]))
                return target
            finally:
                try:
                    cdp.detach()
                except Exception:
                    pass

    def evaluate(self, page: Page, script: str, arg: Any = None) -> Any:
        return page.evaluate(script, arg)
