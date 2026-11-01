# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-01 00:01
# 最后更新: 2026-11-01 12:15
# 文件名: parsers.py
# 主要用途: CITEL / Moodle 页面解析（登录、课程、题目、判题结果与提交历史；bs4/lxml 延迟导入）。
# 文件版本: 2.1.0
"""纯 HTML 解析工具。

解析与网络、UI 分离，便于离线测试；逻辑沿用 B_CHelper 的实现。
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

from .models import (
    Consequence,
    Course,
    CourseStructure,
    IndexRow,
    Part,
    ProblemDetail,
    ProblemRef,
    TestCase,
    TestCaseResult,
)

__version__ = "2.1.0"
__author__ = "Gary"
__all__ = [
    "clean_text",
    "deterministic_structure",
    "extract_activity_id",
    "extract_io_cell",
    "is_logged_in",
    "login_error_message",
    "parse_consequence",
    "parse_courses",
    "parse_course_title",
    "parse_history_submit_ids",
    "parse_login_token",
    "parse_problem_page",
    "parse_programming_index",
    "result_is_terminal",
]

_NEWLINE_MARK: str = "↵"


def _make_soup(html: str) -> Any:
    """使用纯 Python 的 html.parser 解析 HTML。

    选择 html.parser 而非 lxml 是有意为之：
    - 不再需要打包 ~7MB 的 lxml 二进制；
    - bs4 在首次解析时才导入，避免拖慢程序启动；
    - 已用 B_CHelper 的全部页面快照对比，两种后端输出一致。

    Args:
        html: 原始 HTML 文本。

    Returns:
        BeautifulSoup 根节点。
    """
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "html.parser")


def clean_text(value: str) -> str:
    """规范化空白字符与多余空行。

    Args:
        value: 原始文本。

    Returns:
        清理后的文本。
    """
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _block_text(node: Tag) -> str:
    """读取 DOM 节点的可读文本（每个文本块一行）。

    Args:
        node: BeautifulSoup 节点。

    Returns:
        清理后的文本。
    """
    text: str = node.get_text("\n", strip=True)
    return clean_text(text)


def parse_login_token(html: str) -> str:
    """提取登录页的 logintoken。

    Args:
        html: 登录页 HTML。

    Returns:
        token 字符串；不存在时返回空串。
    """
    soup: BeautifulSoup = _make_soup(html)
    field: Tag | None = soup.find("input", {"name": "logintoken"})
    return str(field.get("value", "")) if field else ""


def is_logged_in(html: str) -> bool:
    """判断页面是否处于已登录状态。

    Args:
        html: 页面 HTML。

    Returns:
        已登录返回 ``True``。
    """
    return "page-my-index" in html or "login/logout.php" in html


def login_error_message(html: str) -> str:
    """提取登录失败提示。

    Args:
        html: 登录响应 HTML。

    Returns:
        可读错误信息；未找到时返回空串。
    """
    soup: BeautifulSoup = _make_soup(html)
    node: Tag | None = soup.find(id="loginerrormessage") or soup.find(class_="loginerrors")
    if node:
        return clean_text(node.get_text(" ", strip=True))
    if "Invalid login" in html:
        return "Invalid login"
    return ""


def parse_courses(html: str) -> list[Course]:
    """从仪表盘解析学生已选课程。

    Args:
        html: ``my/`` 页面 HTML。

    Returns:
        课程列表（按页面出现顺序）。
    """
    soup: BeautifulSoup = _make_soup(html)
    found: dict[int, str] = {}
    for link in soup.select('a[href*="course/view.php?id="]'):
        href: str = str(link.get("href", ""))
        match: re.Match[str] | None = re.search(r"[?&]id=(\d+)", href)
        if not match:
            continue
        name: str = clean_text(link.get_text(" ", strip=True))
        if not name:
            continue
        found.setdefault(int(match.group(1)), name)
    return [Course(id=course_id, name=name) for course_id, name in found.items()]


def parse_course_title(html: str, fallback: str = "") -> str:
    """解析课程页面标题。

    Args:
        html: 课程首页 HTML。
        fallback: 标题缺失时的回退值。

    Returns:
        课程名。
    """
    soup: BeautifulSoup = _make_soup(html)
    title: str = soup.title.get_text(" ", strip=True) if soup.title else ""
    if title.startswith("Course:"):
        title = title[len("Course:"):].strip()
    return title or fallback


def _looks_like_index_table(table: Tag) -> bool:
    """判断表格是否为编程题列表。

    Args:
        table: 表格节点。

    Returns:
        命中返回 ``True``。
    """
    headers: list[str] = [th.get_text(" ", strip=True) for th in table.find_all("th")]
    result_headers: set[str] = {
        "My Judge Result",
        "我的判题结果",
        "我的评测结果",
        "评测结果",
    }
    return bool(result_headers.intersection(headers)) and (
        "Topic" in headers or "主题" in headers
    )


def parse_programming_index(html: str) -> list[IndexRow]:
    """解析 "All Programmings" 表格。

    表格最后一行是 Total 汇总行，会被忽略。

    Args:
        html: ``mod/programming/index.php`` 页面 HTML。

    Returns:
        题目行列表。
    """
    soup: BeautifulSoup = _make_soup(html)
    table: Tag | None = next(
        (
            candidate
            for candidate in soup.find_all("table", class_="generaltable")
            if _looks_like_index_table(candidate)
        ),
        None,
    )
    if table is None:
        candidates: list[Tag] = []
        for candidate in soup.find_all("table"):
            rows: list[Tag] = candidate.find_all("tr")
            has_problem_links: bool = any(
                "view.php?id=" in str(link.get("href", ""))
                for row in rows
                for link in row.find_all("a", href=True)
            )
            if has_problem_links and len(rows) > 5:
                candidates.append(candidate)
        if candidates:
            table = max(candidates, key=lambda candidate: len(candidate.find_all("tr")))
    if table is None:
        return []

    rows: list[IndexRow] = []
    for tr in table.find_all("tr"):
        classes: list[str] = [str(item) for item in (tr.get("class") or [])]
        if "lastrow" in classes:
            continue
        cells: list[Tag] = tr.find_all("td", recursive=False)
        if len(cells) < 7:
            continue

        part_name: str = clean_text(cells[0].get_text(" ", strip=True))
        title_link: Tag | None = cells[1].find("a", href=True)
        if not title_link:
            continue
        title: str = clean_text(title_link.get_text(" ", strip=True))
        id_match: re.Match[str] | None = re.search(
            r"[?&]id=(\d+)", str(title_link.get("href", ""))
        )
        if not id_match or not title:
            continue
        module_id: int = int(id_match.group(1))

        my_result: str = clean_text(cells[2].get_text(" ", strip=True))
        activity_id: int | None = None
        for cell in cells[2:6]:
            for link in cell.find_all("a", href=True):
                match: re.Match[str] | None = re.search(
                    r"[?&]a=(\d+)", str(link.get("href", ""))
                )
                if match:
                    activity_id = int(match.group(1))
                    break
            if activity_id is not None:
                break

        try:
            submit_count: int = int(clean_text(cells[5].get_text(" ", strip=True)) or 0)
        except ValueError:
            submit_count = 0

        rows.append(
            IndexRow(
                part_name=part_name or "未分组",
                title=title,
                module_id=module_id,
                activity_id=activity_id,
                my_result=my_result,
                submit_count=submit_count,
            )
        )
    return rows


def extract_io_cell(cell: Tag) -> str:
    """提取编程测试用例的输入/输出文本。

    Moodle 用 ``<li><span>line↵</span></li>`` 表示每一行，``↵`` 表示行尾。

    Args:
        cell: 表格单元格。

    Returns:
        多行文本。
    """
    lines: list[Tag] = cell.find_all("li")
    if not lines:
        return ""
    output: list[str] = []
    for line in lines:
        text: str = line.get_text().replace("\xa0", " ")
        if text.endswith(_NEWLINE_MARK):
            text = text[: -len(_NEWLINE_MARK)]
        output.append(text)
    return "\n".join(output)


def extract_activity_id(html: str) -> int | None:
    """从页面链接中提取活动 ID。

    Args:
        html: 题目页面 HTML。

    Returns:
        活动 ID；未找到返回 ``None``。
    """
    for pattern in (
        r"submit\.php\?a=(\d+)",
        r"result\.php\?a=(\d+)",
        r"history\.php\?a=(\d+)",
        r"view\.php\?a=(\d+)",
    ):
        match: re.Match[str] | None = re.search(pattern, html)
        if match:
            return int(match.group(1))
    return None


def parse_problem_page(html: str, module_id: int = 0) -> ProblemDetail:
    """解析题目详情页。

    Args:
        html: 题目页面 HTML。
        module_id: 题目模块 ID。

    Returns:
        题目详情。
    """
    soup: BeautifulSoup = _make_soup(html)
    main: Tag = soup.find(id="region-main") or soup

    heading: Tag | None = main.find("h1", class_="name") or main.find("h1")
    title: str = (
        clean_text(heading.get_text(" ", strip=True)) if heading else f"题目 {module_id}"
    )

    description: Tag | None = main.find(id="description")
    statement: str = _block_text(description) if description else _block_text(main)

    cases: list[TestCase] = []
    table: Tag | None = main.find("table", id="presetcode-table")
    if table is not None:
        body: Tag = table.find("tbody") or table
        for tr in body.find_all("tr", recursive=False):
            cells: list[Tag] = tr.find_all("td", recursive=False)
            if len(cells) < 5:
                continue
            no_text: str = clean_text(cells[0].get_text(" ", strip=True))
            if not no_text:
                continue
            cases.append(
                TestCase(
                    no=len(cases) + 1,
                    input=extract_io_cell(cells[1]),
                    output=extract_io_cell(cells[2]),
                    time_limit=clean_text(cells[3].get_text(" ", strip=True)),
                    memory_limit=clean_text(cells[4].get_text(" ", strip=True)),
                )
            )

    activity_id: int | None = extract_activity_id(html)
    time_limit: str = cases[0].time_limit if cases else ""
    memory_limit: str = cases[0].memory_limit if cases else ""

    raw_parts: list[str] = [f"题目：{title}", statement]
    if cases:
        raw_parts.append("公开测试用例：")
        for case in cases:
            raw_parts.append(
                f"用例 {case.no} 输入：\n{case.input or '（空）'}\n"
                f"用例 {case.no} 输出：\n{case.output or '（空）'}"
            )
    raw_text: str = "\n\n".join(part for part in raw_parts if part)

    return ProblemDetail(
        title=title,
        statement=statement,
        test_cases=tuple(cases),
        module_id=module_id,
        activity_id=activity_id,
        time_limit=time_limit,
        memory_limit=memory_limit,
        raw_text=raw_text,
    )


def _cell_text(cell: Tag) -> str:
    """读取表格单元格文本。

    Args:
        cell: 单元格节点。

    Returns:
        清理后的文本。
    """
    return clean_text(cell.get_text(" ", strip=True))


def parse_consequence(html: str, submit_id: int | None = None) -> Consequence:
    """解析判题结果页面。

    Args:
        html: ``result.php`` 页面 HTML。
        submit_id: 提交 ID；未提供时尝试从页面提取。

    Returns:
        判题结果。
    """
    soup: BeautifulSoup = _make_soup(html)
    main: Tag = soup.find(id="region-main") or soup
    full_text: str = clean_text(main.get_text("\n", strip=True))

    current_status: str = ""
    status_match: re.Match[str] | None = re.search(
        r"(?:Current Status|当前状态)\s*[:：]\s*(.+)", full_text
    )
    if status_match:
        current_status = status_match.group(1).strip().split("\n")[0].strip()

    compile_node: Tag | None = main.find("div", class_="compilemessage")
    if compile_node is not None:
        compile_message: str = "\n".join(
            clean_text(item.get_text(" ", strip=True))
            for item in compile_node.find_all("li")
        ).strip()
        if not compile_message:
            compile_message = _block_text(compile_node)
    else:
        compile_message = ""

    cases: list[TestCaseResult] = []
    table: Tag | None = main.find("table", id="test-result-detail-table")
    if table is not None:
        headers: list[str] = [th.get_text(" ", strip=True) for th in table.find_all("th")]
        # 列顺序在 Moodle 各语言版本中保持稳定。
        positional: dict[str, int] = {
            "No.": 0,
            "Weight": 1,
            "Time limitation": 2,
            "Memory limitation": 3,
            "Test Input": 4,
            "Expected Output": 5,
            "Test Output": 6,
            "Error message": 7,
            "Time used(seconds)": 8,
            "Memory used": 9,
            "Exit value": 10,
            "Passed": 11,
            "My Judge Result": 12,
        }
        index: dict[str, int] = positional
        if len(headers) == 13:
            by_header: dict[str, int] = {name: position for position, name in enumerate(headers)}
            if all(name in by_header for name in positional):
                index = by_header

        for tr in table.find_all("tr"):
            cells: list[Tag] = tr.find_all("td", recursive=False)
            if len(cells) != 13:
                continue
            no_text: str = _cell_text(cells[0])
            if not no_text.isdigit():
                continue
            passed_text: str = _cell_text(cells[index["Passed"]]).lower()
            cases.append(
                TestCaseResult(
                    no=int(no_text),
                    passed=passed_text in {"yes", "是", "true", "1"},
                    judge_result=_cell_text(cells[index["My Judge Result"]]),
                    test_input=extract_io_cell(cells[index["Test Input"]]),
                    expected_output=extract_io_cell(cells[index["Expected Output"]]),
                    actual_output=extract_io_cell(cells[index["Test Output"]]),
                    error_message=_cell_text(cells[index["Error message"]]),
                    time_used=_cell_text(cells[index["Time used(seconds)"]]),
                    memory_used=_cell_text(cells[index["Memory used"]]),
                    exit_value=_cell_text(cells[index["Exit value"]]),
                )
            )

    passed_count: int = sum(1 for case in cases if case.passed)
    failed_cases: tuple[TestCaseResult, ...] = tuple(
        case for case in cases if not case.passed
    )

    summary_match: re.Match[str] | None = re.search(
        r"There are\s+(\d+)\s+test cases\.\s*Your program has passed\s+(\d+)\s+of them and failed in\s+(\d+)",
        full_text,
        re.I,
    )
    if summary_match:
        total: int = int(summary_match.group(1))
        passed_count = int(summary_match.group(2))
        failed_count: int = int(summary_match.group(3))
        summary: str = f"共 {total} 个测试点，通过 {passed_count} 个，失败 {failed_count} 个。"
    else:
        failed_count = len(failed_cases)
        summary = (
            f"共 {len(cases)} 个测试点，通过 {passed_count} 个，失败 {failed_count} 个。"
            if cases
            else ""
        )

    is_compile_error: bool = bool(compile_message) or "failed to compile" in current_status.lower()
    is_ac: bool = bool(
        not is_compile_error
        and cases
        and passed_count == len(cases)
        and failed_count == 0
    )

    if is_compile_error:
        status: str = "CE: Compile Error"
    elif is_ac:
        status = "AC: Accepted"
    elif failed_cases:
        status = failed_cases[-1].judge_result or "Failed"
    else:
        status = current_status or "Unknown"

    if submit_id is None:
        match: re.Match[str] | None = re.search(r"[?&]submit=(\d+)", html)
        if match:
            submit_id = int(match.group(1))

    return Consequence(
        is_ac=is_ac,
        status=status,
        current_status=current_status,
        summary=summary,
        compile_message=compile_message,
        failed_cases=failed_cases,
        all_cases=tuple(cases),
        submit_id=submit_id,
        raw_text=full_text,
    )


def result_is_terminal(html: str, consequence: Consequence) -> bool:
    """判断判题是否已经结束。

    Args:
        html: 结果页 HTML。
        consequence: 已解析的判题结果。

    Returns:
        结束返回 ``True``。
    """
    if consequence.compile_message:
        return True
    soup: BeautifulSoup = _make_soup(html)
    main: Tag = soup.find(id="region-main") or soup
    if main.find("table", id="test-result-detail-table") is not None:
        return True
    status: str = consequence.current_status.lower()
    if "successfully processed" in status or "failed to compile" in status:
        return True
    if "评测完成" in consequence.current_status or "编译失败" in consequence.current_status:
        return True
    if re.search(r"test cases|测试用例", consequence.raw_text, re.I):
        return True
    return False


def parse_history_submit_ids(html: str) -> list[int]:
    """解析提交历史中的提交 ID（最新在前）。

    Args:
        html: ``history.php`` 页面 HTML。

    Returns:
        提交 ID 列表。
    """
    ids: list[int] = []
    for match in re.finditer(r"submitid=(\d+)", html):
        value: int = int(match.group(1))
        if value not in ids:
            ids.append(value)
    if not ids:
        soup: BeautifulSoup = _make_soup(html)
        for field in soup.find_all("input", class_="diff1"):
            value = str(field.get("value") or "").strip()
            if value.isdigit() and int(value) not in ids:
                ids.append(int(value))
    return ids


def deterministic_structure(rows: list[IndexRow], course_name: str) -> CourseStructure:
    """按页面上的部分字段进行本地分组。

    V2 不再调用 AI 解析课程结构，直接使用页面数据，减少一次 AI 调用与 token 消耗。

    Args:
        rows: 编程题行列表。
        course_name: 课程名。

    Returns:
        课程结构。
    """
    refs: dict[int, ProblemRef] = {
        row.module_id: ProblemRef(
            part_name=row.part_name,
            title=row.title,
            module_id=row.module_id,
            activity_id=row.activity_id,
            my_result=row.my_result,
            submit_count=row.submit_count,
        )
        for row in rows
    }
    parts: list[Part] = []
    by_name: dict[str, Part] = {}
    for row in rows:
        ref: ProblemRef = refs[row.module_id]
        part: Part | None = by_name.get(row.part_name)
        if part is None:
            part = Part(index=len(parts) + 1, name=row.part_name)
            parts.append(part)
            by_name[row.part_name] = part
        part.problems.append(ref)

    for part in parts:
        for number, problem in enumerate(part.problems, 1):
            problem.number = number
    return CourseStructure(course_name=course_name, parts=parts, source="local")
