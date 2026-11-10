# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-10 13:00
# 文件名: document_page.py
# 主要用途: 文档页 Page Object：打开/重试、阅读器就绪、PDF 翻页与下载链接收集。
# 文件版本: 4.4.0
"""文档页 Page Object。"""
from __future__ import annotations

import time
from typing import Any

from ..actions.base import ActionCancelled, ActionUnavailable
from ..models import Task
from .base import PageObject
from .icourse163 import DOCUMENT_SELECTORS, close_modals, open_route, page_block_reason

__version__ = "4.4.0"
__author__ = "Gary"
__all__ = [
    "DocumentPage",
    "MAX_PDF_PAGES",
    "PDF_PAGE_WAIT_MS",
    "PDF_READY_TIMEOUT_MS",
    "PDF_STATUS_JS",
]

PDF_NEXT_TIMEOUT_MS = 5_000
PDF_PAGE_WAIT_MS = 700
PDF_READY_TIMEOUT_MS = 15_000
MAX_PDF_PAGES = 300

PDF_STATUS_JS = r"""
() => {
  const parse = (value) => {
    const match = String(value || '').match(/(\d+)\s*\/\s*(\d+)/);
    return match ? [parseInt(match[1]), parseInt(match[2])] : null;
  };
  const modern = document.querySelector('.mooc-docs-reader__page-status');
  if (modern) {
    const pair = parse(modern.innerText) || [0, 0];
    if (pair[1] > 0) {
      return {kind: 'modern', current: pair[0], total: pair[1]};
    }
  }
  // 2026-11 的 v2 阅读器没有独立页码节点，页码文本嵌在 .pdf-unit-renderer 内。
  const v2 = document.querySelector('.pdf-unit-renderer, .pdf-unit-reader');
  if (v2) {
    const pairs = [...String(v2.innerText || '').matchAll(
      /(\d+)\s*\/\s*(\d+)/g
    )].map((match) => [parseInt(match[1]), parseInt(match[2])]);
    const pair = pairs.find((item) => item[1] > 0 && item[1] <= 1000
      && item[0] <= item[1]);
    if (pair) {
      return {kind: 'modern', current: pair[0], total: pair[1]};
    }
  }
  const currentInput = document.querySelector(
    '.ux-h5pdfreader_container_footer_pages_in'
  );
  const totalNode = document.querySelector(
    '.ux-h5pdfreader_container_footer_pages_total'
  );
  if (currentInput || totalNode) {
    const current = parseInt(currentInput?.value || '0') || 0;
    const pair = parse(totalNode?.innerText || '') || [0, 0];
    return {kind: 'legacy', current: current || pair[0], total: pair[1]};
  }
  return {kind: 'none', current: 0, total: 0};
}
"""


class DocumentPage(PageObject):
    """文档单元页。"""

    def open(self, base: str, hash_path: str, url: str, task: Task) -> Any:
        """打开文档页；首次失败换新 Page 重试一次。"""
        page = self.ctx.acquire_page()
        try:
            open_route(page, base, hash_path)
            self.page = page
            return page
        except ActionCancelled:
            raise
        except Exception as exc:
            self.warn(f"文档页首次打开失败：{exc}")
            self.page = page
            self.screenshot(f".artifacts/document-{task.unit_id}-failed.png")
            try:
                page.close()
            except Exception:
                pass
        self.check_cancel()
        retry_page = self.ctx.session.new_page()
        self.ctx.page = retry_page
        self.page = retry_page
        try:
            try:
                open_route(retry_page, base, hash_path)
            except ActionCancelled:
                raise
            except Exception:
                retry_page.goto(url, wait_until="commit", timeout=45_000)
                retry_page.wait_for_timeout(2500)
            return retry_page
        except ActionCancelled:
            raise
        except Exception as exc:
            self.screenshot(f".artifacts/document-{task.unit_id}-failed.png")
            raise ActionUnavailable(
                f"文档页打开失败：{exc}；URL：{url}"
            ) from exc

    def wait_ready(self, timeout_ms: int = 15_000) -> None:
        """等待阅读器/下载链接/章节框架出现。"""
        assert self.page is not None
        deadline = time.monotonic() + max(0, timeout_ms) / 1000
        started = time.monotonic()
        selector = (
            "a.j-downpdf, a.j-downtxt, .mooc-docs-reader__page-status, "
            ".pdf-unit-renderer, .pdf-unit-reader, "
            ".ux-h5pdfreader_container_footer_pages_total"
        )
        while time.monotonic() < deadline:
            self.check_cancel()
            try:
                if self.page.locator(selector).count() > 0:
                    return
            except Exception:
                return
            if time.monotonic() - started >= 3:
                if page_block_reason(self.page):
                    return
                try:
                    if self.page.locator(
                        ".m-learnChapterNormal, .m-learnChapterList"
                    ).count() > 0:
                        return
                except Exception:
                    return
            try:
                self.page.wait_for_timeout(500)
            except Exception as exc:
                raise ActionUnavailable(f"文档页已关闭：{exc}") from exc

    def close_modals(self) -> None:
        """关闭页面弹窗。"""
        assert self.page is not None
        close_modals(self.page)

    def blocked_reason(self) -> str:
        """返回页面不可用原因。"""
        assert self.page is not None
        return page_block_reason(self.page)

    def has_document_content(self) -> bool:
        """判断页面是否已有文档阅读器/下载链接。"""
        assert self.page is not None
        try:
            return self.page.locator(
                "a.j-downpdf, a.j-downtxt, .pdf-unit-renderer, "
                ".pdf-unit-reader, .mooc-docs-reader__page-status, "
                ".ux-h5pdfreader_container_footer_pages_total"
            ).count() > 0
        except Exception:
            return False

    def pdf_status(self) -> dict[str, Any]:
        """读取 PDF 阅读器页码。"""
        assert self.page is not None
        try:
            value = self.page.evaluate(PDF_STATUS_JS)
            return value if isinstance(value, dict) else {
                "kind": "none", "current": 0, "total": 0
            }
        except Exception:
            return {"kind": "none", "current": 0, "total": 0}

    def wait_pdf_ready(self) -> dict[str, Any]:
        """等待新版/旧版 PDF 阅读器出现。"""
        assert self.page is not None
        deadline = time.monotonic() + PDF_READY_TIMEOUT_MS / 1000
        status = self.pdf_status()
        while time.monotonic() < deadline:
            self.check_cancel()
            kind = str(status.get("kind") or "none")
            total = int(status.get("total") or 0)
            if kind == "legacy" or (kind == "modern" and total > 0):
                return status
            self.page.wait_for_timeout(500)
            status = self.pdf_status()
        return status

    def advance_pdf(self) -> tuple[bool, int]:
        """把 PDF 阅读器翻到最后一页。"""
        assert self.page is not None
        status = self.pdf_status()
        kind = str(status.get("kind") or "none")
        total = int(status.get("total") or 0)
        if kind == "none" or total <= 0:
            return False, total
        if int(status.get("current") or 0) >= total:
            return True, total

        next_selectors = (
            (
                'button[aria-label="下一页"]',
                '[aria-label="下一页"]',
                'button:has-text("下一页")',
            )
            if kind == "modern"
            else (".ux-h5pdfreader_container_footer_pages_next",)
        )
        self.info(f"文档共 {total} 页，正在翻到最后一页…")
        stalled = 0
        for _ in range(min(total + 2, MAX_PDF_PAGES)):
            self.check_cancel()
            status = self.pdf_status()
            current = int(status.get("current") or 0)
            total = int(status.get("total") or total)
            if current >= total:
                break
            button = None
            for selector in next_selectors:
                candidate = self.page.locator(selector).first
                try:
                    if candidate.count() > 0 and candidate.is_visible():
                        button = candidate
                        break
                except Exception:
                    continue
            if button is None:
                break
            try:
                classes = str(button.get_attribute("class") or "")
                if "disable" in classes or "disabled" in classes:
                    break
                button.click(timeout=PDF_NEXT_TIMEOUT_MS)
            except Exception:
                break
            self.page.wait_for_timeout(PDF_PAGE_WAIT_MS)
            after = int(self.pdf_status().get("current") or 0)
            if after <= current:
                stalled += 1
                if stalled >= 2:
                    break
                self.page.wait_for_timeout(PDF_PAGE_WAIT_MS)
            else:
                stalled = 0
        self.page.wait_for_timeout(1500)
        final = self.pdf_status()
        done = int(final.get("current") or 0) >= int(final.get("total") or total)
        return done, int(final.get("total") or total)

    def collect_links(self, task: Task) -> list[tuple[str, str]]:
        """收集文档下载链接。"""
        assert self.page is not None
        selector = (
            f"{DOCUMENT_SELECTORS['pdf']}, {DOCUMENT_SELECTORS['attachment']}, "
            'a:has-text("文档下载"), a:has-text("附件下载")'
        )
        try:
            self.page.wait_for_selector(selector, timeout=20_000)
        except Exception:
            return []
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            self.check_cancel()
            links: list[tuple[str, str]] = []
            seen: set[str] = set()
            for css in (
                DOCUMENT_SELECTORS["pdf"],
                DOCUMENT_SELECTORS["attachment"],
                'a:has-text("文档下载")',
                'a:has-text("附件下载")',
            ):
                try:
                    elements = self.page.locator(css).all()
                except Exception:
                    continue
                for element in elements:
                    try:
                        href = str(element.get_attribute("href") or "").strip()
                        text = str(element.inner_text() or "").strip()
                    except Exception:
                        continue
                    if not href or href.startswith("javascript:"):
                        continue
                    if href in seen:
                        continue
                    seen.add(href)
                    links.append((href, text))
            if links:
                return links
            self.page.wait_for_timeout(500)
        return []
