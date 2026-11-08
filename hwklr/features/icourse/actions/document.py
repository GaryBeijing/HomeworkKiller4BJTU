# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: document.py
# 主要用途: 文档任务：翻页、下载课件与完成状态验证。
# 文件版本: 4.0.0
"""文档/课件任务：下载课件并刷新完成状态。

文档单元（``contentType=3``）的页面会加载 PDF 阅读器，站点只有在
``pageNum == totalPage`` 时才发送 ``finished:true``。本动作：
1. 打开文档页；
2. 下载 ``a.j-downpdf`` / ``a.j-downtxt`` 指向的课件；
3. 对可翻页的阅读器逐页翻到最后一页，让站点自己发送完成进度；
4. 由命令层重新读取 learned 状态确认是否真的完成（文档以
   ``viewStatus=5`` 为完成信号）。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from ..models import DOCUMENT_KIND, DONE, Course, Task
from ..pages import (
    DOCUMENT_SELECTORS,
    close_modals,
    learn_url,
    open_route,
    page_block_reason,
)
from ..paths import documents_dir
from .base import ActionCancelled, ActionContext

DOCUMENT_CONTENT_TYPE = 3
DOCUMENT_READY_TIMEOUT_MS = 20_000
DOCUMENT_DOWNLOAD_TIMEOUT_MS = 60_000
PDF_NEXT_TIMEOUT_MS = 5_000
PDF_PAGE_WAIT_MS = 700
PDF_READY_TIMEOUT_MS = 15_000
MAX_PDF_PAGES = 300
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

PDF_STATUS_JS = r"""
() => {
  const parse = (value) => {
    const match = String(value || '').match(/(\d+)\s*\/\s*(\d+)/);
    return match ? [parseInt(match[1]), parseInt(match[2])] : null;
  };
  const modern = document.querySelector('.mooc-docs-reader__page-status');
  if (modern) {
    const pair = parse(modern.innerText) || [0, 0];
    return {kind: 'modern', current: pair[0], total: pair[1]};
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


def select_pending_documents(
    course: Course,
    *,
    start: Task | None = None,
    limit: int | None = None,
) -> list[Task]:
    """按课程顺序选择未完成文档任务。"""
    all_tasks = course.tasks
    documents = [
        task
        for task in all_tasks
        if task.kind == DOCUMENT_KIND
        and (task.content_type in (None, DOCUMENT_CONTENT_TYPE))
    ]
    if start is not None and start in all_tasks:
        begin = all_tasks.index(start)
        documents = [task for task in documents if all_tasks.index(task) >= begin]
    pending = [task for task in documents if task.status != DONE]
    if limit is not None:
        pending = pending[: max(0, limit)]
    return pending


def build_document_progress_payload(
    course: Course,
    task: Task,
    *,
    finished: bool = True,
    page_num: int = 1,
    learned_video_time_count: int = 1,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """构造与站点 PDF 阅读器一致的完成进度请求体。"""
    return {
        "dto": {
            "unitId": int(task.unit_id or 0),
            "finished": bool(finished),
            "contentType": int(task.content_type or DOCUMENT_CONTENT_TYPE),
            "index": 0,
            "pageNum": max(1, int(page_num or 1)),
            "courseId": int(course.course_id or 0),
            "lessonId": int(task.lesson_id or 0),
            "termId": int(course.term_id or 0),
            "lastLearnTime": int(
                now_ms if now_ms is not None else time.time() * 1000
            ),
            "learnedVideoTimeCount": int(learned_video_time_count),
        }
    }


def _repair_mojibake(text: str) -> str:
    """修复服务端把 UTF-8 文件名按 Latin-1 解码造成的乱码。"""
    try:
        if any(ord(char) > 127 for char in text):
            repaired = text.encode("latin-1").decode("utf-8")
            if repaired:
                return repaired
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return text


def safe_filename(name: str, fallback: str) -> str:
    """清理 Windows 非法字符，避免路径穿越。"""
    text = _repair_mojibake(unquote(str(name or "")))
    text = text.replace("\\", "/").rsplit("/", 1)[-1]
    text = INVALID_FILENAME_CHARS.sub("_", text).strip().strip(".")
    if len(text) > 120:
        stem, dot, suffix = text.rpartition(".")
        if dot and len(suffix) <= 10:
            text = stem[: 120 - len(suffix) - 1] + "." + suffix
        else:
            text = text[:120]
    return text or fallback


def filename_from_disposition(value: str | None) -> str:
    """从 Content-Disposition 提取文件名（支持 RFC 5987）。"""
    text = str(value or "")
    if not text:
        return ""
    match = re.search(
        r"filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)", text
    )
    if match:
        return unquote(match.group(1).strip().strip('"'))
    match = re.search(r'filename\s*=\s*"([^"]+)"', text, re.IGNORECASE)
    if match:
        return unquote(match.group(1))
    match = re.search(r"filename\s*=\s*([^;]+)", text, re.IGNORECASE)
    if match:
        return unquote(match.group(1).strip().strip('"'))
    return ""


def filename_from_url(url: str, fallback: str) -> str:
    """优先使用链接的 ``download`` 参数，其次 URL basename。"""
    parsed = urlparse(str(url or ""))
    query = parse_qs(parsed.query)
    candidates = query.get("download") or query.get("filename") or []
    name = candidates[0] if candidates else ""
    if not name:
        name = unquote(Path(parsed.path).name)
    return safe_filename(name, fallback)


def pdf_page_count(data: bytes) -> int:
    """尽量从 PDF 字节里数页数；解析失败按 1 页处理。"""
    if not data:
        return 1
    pages = len(re.findall(rb"/Type\s*/Page(?!s)", data))
    if pages:
        return pages
    counts = [int(value) for value in re.findall(rb"/Count\s+(\d+)", data)]
    if counts:
        return max(1, max(counts))
    return 1


def progress_response_ok(raw: Any) -> bool:
    """判断 saveMocContentLearn 的返回是否成功。"""
    if isinstance(raw, dict):
        return str(raw.get("code")) == "0"
    text = str(raw or "")
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return False
    return isinstance(payload, dict) and str(payload.get("code")) == "0"


@dataclass
class DocumentResult:
    task: Task
    url: str
    download_urls: list[str] = field(default_factory=list)
    download_paths: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    marked: bool = False
    message: str = ""
    screenshot: str = ""
    status_before: str = ""
    status_after: str = ""
    verified: bool | None = None
    elapsed: float = 0.0


class DocumentAction:
    def __init__(self, ctx: ActionContext) -> None:
        self.ctx = ctx

    def run(
        self,
        course: Course,
        tasks: list[Task],
        *,
        download: bool = True,
        output_dir: Path | str | None = None,
        dry_run: bool = False,
    ) -> list[DocumentResult]:
        results: list[DocumentResult] = []
        for index, task in enumerate(tasks, 1):
            self.ctx.check_cancel()
            self.ctx.info(
                f"[{index}/{len(tasks)}] {task.chapter} / {task.lesson} / {task.name}"
            )
            results.append(
                self.run_one(
                    course,
                    task,
                    download=download,
                    output_dir=output_dir,
                    dry_run=dry_run,
                )
            )
        return results

    def run_one(
        self,
        course: Course,
        task: Task,
        *,
        download: bool = True,
        output_dir: Path | str | None = None,
        dry_run: bool = False,
    ) -> DocumentResult:
        self.ctx.check_cancel()
        if task.kind != DOCUMENT_KIND:
            raise ActionCancelled(f"任务「{task.name}」不是文档任务")
        if not course.school_short_name or not course.course_id:
            raise ActionCancelled("课程缺少 schoolShortName/courseId，无法构造文档页 URL")
        if not task.unit_id or not task.lesson_id:
            raise ActionCancelled(f"任务「{task.name}」缺少 unitId/lessonId")

        base = learn_url(
            course.school_short_name,
            course.course_id,
            course.term_id,
            spoc=course.is_spoc,
        )
        hash_path = (
            f"#/learn/content?type=detail&id={int(task.lesson_id)}"
            f"&cid={int(task.unit_id)}"
        )
        url = base + hash_path
        started = time.monotonic()
        page = self.ctx.acquire_page()
        open_route(page, base, hash_path)
        close_modals(page)
        blocked = page_block_reason(page)
        if blocked:
            self.ctx.session.screenshot(
                page, f".artifacts/document-blocked-{task.unit_id}.png"
            )
            raise ActionCancelled(f"文档页无法访问：{blocked}。当前 URL：{page.url}")

        result = DocumentResult(task=task, url=url, status_before=task.status)
        fallback = f"document-{task.unit_id}.pdf"
        if dry_run:
            links = self._collect_links(page, task)
            result.download_urls = [item[0] for item in links]
            status = self._wait_pdf_ready(page)
            result.payload = build_document_progress_payload(
                course,
                task,
                finished=False,
                page_num=int(status.get("total") or 1),
            )
            result.message = "dry-run：仅预览下载地址和完成请求，未下载/未写入"
            result.screenshot = str(
                self.ctx.session.screenshot(
                    page, f".artifacts/document-{task.unit_id}-dryrun.png"
                )
            )
            result.elapsed = time.monotonic() - started
            return result

        self._wait_pdf_ready(page)
        pdf_done, pdf_total = self._advance_pdf(page)
        links = self._collect_links(page, task)
        result.download_urls = [item[0] for item in links]
        result.payload = build_document_progress_payload(
            course, task, finished=pdf_done, page_num=pdf_total or 1
        )

        pdf_bytes = b""
        if download and links:
            target_dir = self._target_dir(course, output_dir)
            for href, _text in links:
                absolute = urljoin(page.url, href)
                filename = filename_from_url(absolute, fallback)
                try:
                    response = self.ctx.session.context.request.get(
                        absolute,
                        headers={"Referer": page.url},
                        timeout=DOCUMENT_DOWNLOAD_TIMEOUT_MS,
                    )
                    if not response.ok:
                        result.message = f"下载失败：HTTP {response.status}"
                        continue
                    data = response.body()
                    disposition = response.headers.get(
                        "content-disposition", ""
                    )
                    filename = safe_filename(
                        filename_from_disposition(disposition) or filename,
                        fallback,
                    )
                    target = self._unique_path(target_dir, filename)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    result.download_paths.append(str(target))
                    if not pdf_bytes and data[:5] == b"%PDF-":
                        pdf_bytes = data
                except Exception as exc:
                    result.message = f"下载失败：{exc}"
            if not result.download_paths:
                result.message = result.message or "没有下载到任何课件"

        page_num = pdf_page_count(pdf_bytes) if pdf_bytes else 1
        # 新版 PDF 阅读器：翻到最后一页时站点自己发送 finished:true；
        # 旧版/无阅读器页面：打开页面后站点写 viewStatus=5 即视为完成。
        # 不能直接补发 finished:true（实测会被服务端以 -10006 拒绝）。
        result.payload = build_document_progress_payload(
            course,
            task,
            finished=pdf_done if pdf_total else False,
            page_num=pdf_total or page_num,
        )
        result.marked = pdf_done if pdf_total else True
        if result.download_paths:
            result.message = (
                f"已保存 {len(result.download_paths)} 个课件，"
                + (
                    "并翻到文档最后一页"
                    if pdf_total and pdf_done
                    else "并打开文档页"
                )
            )
        else:
            result.message = (
                "已翻到文档最后一页"
                if pdf_total and pdf_done
                else "已打开文档页"
            )
        result.message += "，等待 learned 状态刷新"
        self.ctx.info(
            "已翻到文档最后一页，等待服务端刷新学习状态…"
            if pdf_total and pdf_done
            else "已打开文档页，等待服务端刷新学习状态…"
        )

        suffix = "done"
        result.screenshot = str(
            self.ctx.session.screenshot(
                page, f".artifacts/document-{task.unit_id}-{suffix}.png"
            )
        )
        result.elapsed = time.monotonic() - started
        return result

    # ------------------------------------------------------------------ 页面
    @staticmethod
    def _pdf_status(page) -> dict[str, Any]:
        try:
            value = page.evaluate(PDF_STATUS_JS)
            return value if isinstance(value, dict) else {
                "kind": "none", "current": 0, "total": 0
            }
        except Exception:
            return {"kind": "none", "current": 0, "total": 0}

    def _wait_pdf_ready(self, page) -> dict[str, Any]:
        """等待新版/旧版 PDF 阅读器出现（最多 15 秒）。"""
        deadline = time.monotonic() + PDF_READY_TIMEOUT_MS / 1000
        status = self._pdf_status(page)
        while time.monotonic() < deadline:
            self.ctx.check_cancel()
            kind = str(status.get("kind") or "none")
            total = int(status.get("total") or 0)
            if kind == "legacy" or (kind == "modern" and total > 0):
                return status
            page.wait_for_timeout(500)
            status = self._pdf_status(page)
        return status

    def _advance_pdf(self, page) -> tuple[bool, int]:
        """把 PDF 阅读器翻到最后一页，让站点自己发送 finished:true。

        新版页面使用 ``/front-mooc-learn/api/learn/content/progress``，
        旧版页面使用 ``saveMocContentLearn.rpc``；两种都只在最后一页
        把 ``finished`` 置为 true。没有阅读器时返回 (False, 0)。
        """
        status = self._pdf_status(page)
        kind = str(status.get("kind") or "none")
        current = int(status.get("current") or 0)
        total = int(status.get("total") or 0)
        if kind == "none" or total <= 0:
            return False, total
        if current >= total:
            return True, total

        next_selector = (
            'button[aria-label="下一页"]'
            if kind == "modern"
            else ".ux-h5pdfreader_container_footer_pages_next"
        )
        self.ctx.info(f"文档共 {total} 页，正在翻到最后一页…")
        stalled = 0
        for _ in range(min(total + 2, MAX_PDF_PAGES)):
            self.ctx.check_cancel()
            status = self._pdf_status(page)
            current = int(status.get("current") or 0)
            total = int(status.get("total") or total)
            if current >= total:
                break
            button = page.locator(next_selector).first
            try:
                if button.count() == 0 or not button.is_visible():
                    break
                classes = str(button.get_attribute("class") or "")
                if "disable" in classes or "disabled" in classes:
                    break
                button.click(timeout=PDF_NEXT_TIMEOUT_MS)
            except Exception:
                break
            page.wait_for_timeout(PDF_PAGE_WAIT_MS)
            after = int(self._pdf_status(page).get("current") or 0)
            if after <= current:
                stalled += 1
                if stalled >= 2:
                    break
                page.wait_for_timeout(PDF_PAGE_WAIT_MS)
            else:
                stalled = 0
        # 最后一页的 progress 请求是异步的，给它一点时间落库。
        page.wait_for_timeout(1500)
        final = self._pdf_status(page)
        done = int(final.get("current") or 0) >= int(final.get("total") or total)
        return done, int(final.get("total") or total)

    @staticmethod
    def _collect_links(page, task: Task) -> list[tuple[str, str]]:
        """等待下载链接出现，返回 [(href, text)]。"""
        selector = (
            f"{DOCUMENT_SELECTORS['pdf']}, {DOCUMENT_SELECTORS['attachment']}, "
            'a:has-text("文档下载"), a:has-text("附件下载")'
        )
        try:
            page.wait_for_selector(selector, timeout=DOCUMENT_READY_TIMEOUT_MS)
        except Exception:
            return []
        deadline = time.monotonic() + DOCUMENT_READY_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            self.ctx.check_cancel()
            links: list[tuple[str, str]] = []
            seen: set[str] = set()
            for css in (
                DOCUMENT_SELECTORS["pdf"],
                DOCUMENT_SELECTORS["attachment"],
                'a:has-text("文档下载")',
                'a:has-text("附件下载")',
            ):
                for element in page.locator(css).all():
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
            page.wait_for_timeout(500)
        return []

    @staticmethod
    def _target_dir(course: Course, output_dir: Path | str | None) -> Path:
        root = Path(output_dir).expanduser() if output_dir else documents_dir()
        folder = safe_filename(
            course.name or str(course.term_id),
            str(course.term_id),
        )
        return root / folder

    @staticmethod
    def _unique_path(directory: Path, filename: str) -> Path:
        target = directory / filename
        if not target.exists():
            return target
        stem = target.stem
        suffix = target.suffix
        for index in range(2, 1000):
            candidate = directory / f"{stem}-{index}{suffix}"
            if not candidate.exists():
                return candidate
        return directory / f"{stem}-{int(time.time())}{suffix}"

