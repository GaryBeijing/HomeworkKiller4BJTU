# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 最后更新: 2026-11-10 13:00
# 文件名: document.py
# 主要用途: 文档任务：翻页、下载课件与完成状态验证。
# 文件版本: 4.4.0
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
from ..pages import learn_url
from ..pages.document_page import (
    MAX_PDF_PAGES,
    PDF_NEXT_TIMEOUT_MS,
    PDF_PAGE_WAIT_MS,
    PDF_READY_TIMEOUT_MS,
    PDF_STATUS_JS,
    DocumentPage,
)
from ..paths import documents_dir
from .base import (
    ActionCancelled,
    ActionContext,
    ActionUnavailable,
)

DOCUMENT_CONTENT_TYPE = 3
DOCUMENT_READY_TIMEOUT_MS = 20_000
DOCUMENT_DOWNLOAD_TIMEOUT_MS = 60_000


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
            raise ActionUnavailable(f"任务「{task.name}」不是文档任务")
        if not course.school_short_name or not course.course_id:
            raise ActionUnavailable("课程缺少 schoolShortName/courseId，无法构造文档页 URL")
        if not task.unit_id or not task.lesson_id:
            raise ActionUnavailable(f"任务「{task.name}」缺少 unitId/lessonId")

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
        page = self._open_page(base, hash_path, url, task)
        document = DocumentPage(self.ctx, page)
        document.close_modals()
        document.wait_ready()
        blocked = document.blocked_reason()
        if blocked and not document.has_document_content():
            document.screenshot(
                f".artifacts/document-blocked-{task.unit_id}.png"
            )
            raise ActionUnavailable(
                f"文档页无法访问：{blocked}。当前 URL：{page.url}"
            )

        result = DocumentResult(task=task, url=url, status_before=task.status)
        fallback = f"document-{task.unit_id}.pdf"
        if dry_run:
            links = document.collect_links(task)
            result.download_urls = [item[0] for item in links]
            status = document.wait_pdf_ready()
            result.payload = build_document_progress_payload(
                course,
                task,
                finished=False,
                page_num=int(status.get("total") or 1),
            )
            result.message = "dry-run：仅预览下载地址和完成请求，未下载/未写入"
            result.screenshot = document.screenshot(
                f".artifacts/document-{task.unit_id}-dryrun.png"
            )
            result.elapsed = time.monotonic() - started
            return result

        document.wait_pdf_ready()
        pdf_done, pdf_total = document.advance_pdf()
        links = document.collect_links(task)
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
        result.screenshot = document.screenshot(
            f".artifacts/document-{task.unit_id}-{suffix}.png"
        )
        result.elapsed = time.monotonic() - started
        return result

    # ------------------------------------------------------------------ 页面
    def _open_page(
        self, base: str, hash_path: str, url: str, task: Task
    ) -> Any:
        """兼容旧测试的打开文档页入口。"""
        return DocumentPage(self.ctx).open(base, hash_path, url, task)

    def _wait_page_ready(self, page, *, timeout_ms: int = 15_000) -> None:
        """兼容旧测试的页面就绪入口。"""
        DocumentPage(self.ctx, page).wait_ready(timeout_ms)

    @staticmethod
    def _pdf_status(page) -> dict[str, Any]:
        """兼容旧测试的 PDF 状态入口。"""
        return DocumentPage(None, page).pdf_status()  # type: ignore[arg-type]

    def _wait_pdf_ready(self, page) -> dict[str, Any]:
        """兼容旧测试的 PDF 就绪入口。"""
        return DocumentPage(self.ctx, page).wait_pdf_ready()

    def _advance_pdf(self, page) -> tuple[bool, int]:
        """兼容旧测试的 PDF 翻页入口。"""
        return DocumentPage(self.ctx, page).advance_pdf()

    @staticmethod
    def _collect_links(page, task: Task) -> list[tuple[str, str]]:
        """兼容旧测试的下载链接入口。"""
        return DocumentPage(None, page).collect_links(task)  # type: ignore[arg-type]

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

