# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-01 00:01
# 最后更新: 2026-11-01 12:15
# 文件名: site.py
# 主要用途: CITEL / Moodle 课程平台的同步 HTTP 客户端（登录、课程、提交与判题轮询；requests 延迟导入）。
# 文件版本: 2.1.0
"""CITEL 课程平台客户端。

V2 由 CLI 的异步实现改为同步方法：调用发生在 pywebview 的桥接线程或
题解模式的后台工作线程中，不会阻塞 UI 主线程。
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import requests

from . import parsers
from .models import Consequence, Course, IndexRow, ProblemDetail

__version__ = "2.1.0"
__author__ = "Gary"
__all__ = [
    "BASE_URL",
    "DEFAULT_TIMEOUT",
    "MoodleError",
    "MoodleSite",
    "SubmitError",
    "get_consequence",
]

BASE_URL: str = "https://citel.bjtu.edu.cn/mlsv3"
DEFAULT_TIMEOUT: float = 30.0


class MoodleError(RuntimeError):
    """访问课程平台时发生的可读异常。"""


class SubmitError(MoodleError):
    """网站拒绝提交。"""


def _empty_consequence(submit_id: int | None = None) -> Consequence:
    """构造空判题结果。

    Args:
        submit_id: 提交 ID。

    Returns:
        空的 :class:`Consequence`。
    """
    return Consequence(
        is_ac=False,
        status="Unknown",
        current_status="",
        summary="",
        compile_message="",
        failed_cases=(),
        all_cases=(),
        submit_id=submit_id,
        raw_text="",
    )


class MoodleSite:
    """CITEL 课程平台客户端。"""

    def __init__(self, base_url: str = BASE_URL, timeout: float = DEFAULT_TIMEOUT) -> None:
        """初始化客户端。

        Args:
            base_url: 平台根地址。
            timeout: 普通请求超时秒数。
        """
        # 延迟导入 requests：只有真正访问 CITEL 时才加载网络库，减少启动时间。
        import requests

        self.base_url: str = base_url.rstrip("/")
        self.timeout: float = timeout
        self._request_error: type[BaseException] = requests.RequestException
        self.session: requests.Session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })

    def _url(self, path: str) -> str:
        """拼接完整 URL。

        Args:
            path: 相对路径或完整 URL。

        Returns:
            完整 URL。
        """
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def _get_sync(self, path: str, **params: Any) -> requests.Response:
        """发送 GET 请求。

        Args:
            path: 相对路径。
            **params: 查询参数。

        Returns:
            响应对象。

        Raises:
            MoodleError: 网络或 HTTP 错误时抛出。
        """
        try:
            response: requests.Response = self.session.get(
                self._url(path), params=params or None, timeout=self.timeout
            )
            response.raise_for_status()
            return response
        except self._request_error as exc:
            raise MoodleError(f"访问课程网站失败：{exc}") from exc

    def _post_sync(
        self, path: str, data: dict[str, str], timeout: float
    ) -> requests.Response:
        """发送 POST 请求。

        Args:
            path: 相对路径。
            data: 表单数据。
            timeout: 超时秒数。

        Returns:
            响应对象。

        Raises:
            MoodleError: 网络或 HTTP 错误时抛出。
        """
        try:
            response: requests.Response = self.session.post(
                self._url(path), data=data, timeout=timeout, allow_redirects=True
            )
            response.raise_for_status()
            return response
        except self._request_error as exc:
            raise MoodleError(f"向课程网站提交请求失败：{exc}") from exc

    def login(self, username: str, password: str) -> tuple[bool, str]:
        """登录 CITEL。

        Args:
            username: 学号。
            password: 密码（本课程平台固定为 ``学号@Bjtu``）。

        Returns:
            ``(是否成功, 错误信息)``。
        """
        page: requests.Response = self._get_sync("login/index.php")
        token: str = parsers.parse_login_token(page.text)
        if not token:
            return False, "登录页面中没有找到 logintoken，网站结构可能已变化。"
        response: requests.Response = self._post_sync(
            "login/index.php",
            {
                "username": username,
                "password": password,
                "logintoken": token,
                "rememberusername": "1",
            },
            timeout=self.timeout,
        )
        if parsers.is_logged_in(response.text):
            return True, ""
        message: str = parsers.login_error_message(response.text)
        return False, message or "登录失败，请检查用户名或密码。"

    def get_courses(self) -> list[Course]:
        """读取学生已选课程。

        Returns:
            课程列表。

        Raises:
            MoodleError: 未登录或解析失败时抛出。
        """
        response: requests.Response = self._get_sync("my/")
        if not parsers.is_logged_in(response.text):
            raise MoodleError("当前会话未登录，无法读取课程列表。")
        courses: list[Course] = parsers.parse_courses(response.text)
        if not courses:
            raise MoodleError("没有在仪表盘中找到任何课程。")
        return courses

    def get_course_page(self, course_id: int) -> tuple[str, str]:
        """读取课程首页。

        Args:
            course_id: 课程 ID。

        Returns:
            ``(课程标题, HTML)``。
        """
        response: requests.Response = self._get_sync("course/view.php", id=course_id)
        return parsers.parse_course_title(response.text), response.text

    def get_index_rows(self, course_id: int) -> list[IndexRow]:
        """读取课程编程题列表。

        Args:
            course_id: 课程 ID。

        Returns:
            题目行列表。

        Raises:
            MoodleError: 未解析到编程题时抛出。
        """
        response: requests.Response = self._get_sync("mod/programming/index.php", id=course_id)
        rows: list[IndexRow] = parsers.parse_programming_index(response.text)
        if not rows:
            raise MoodleError(
                "没有从课程中解析到编程题。请确认该课程包含 Programming Practice 活动。"
            )
        return rows

    def get_my_results(self, course_id: int) -> dict[int, tuple[str, int]]:
        """读取每道题的最新判题状态与提交次数。

        Args:
            course_id: 课程 ID。

        Returns:
            ``{module_id: (结果, 提交次数)}``。
        """
        rows: list[IndexRow] = self.get_index_rows(course_id)
        return {
            row.module_id: (row.my_result, row.submit_count) for row in rows
        }

    def get_problem(self, module_id: int) -> ProblemDetail:
        """读取题目详情。

        Args:
            module_id: 题目模块 ID。

        Returns:
            题目详情。
        """
        response: requests.Response = self._get_sync(
            "mod/programming/view.php", id=module_id
        )
        return parsers.parse_problem_page(response.text, module_id=module_id)

    def resolve_activity_id(self, module_id: int) -> int | None:
        """从题目页面解析活动 ID。

        Args:
            module_id: 题目模块 ID。

        Returns:
            活动 ID；未找到返回 ``None``。
        """
        response: requests.Response = self._get_sync(
            "mod/programming/view.php", id=module_id
        )
        return parsers.extract_activity_id(response.text)

    def get_submit_ids(self, activity_id: int) -> list[int]:
        """读取提交历史中的提交 ID。

        Args:
            activity_id: 活动 ID。

        Returns:
            提交 ID 列表（最新在前）。
        """
        response: requests.Response = self._get_sync(
            "mod/programming/history.php", a=activity_id
        )
        return parsers.parse_history_submit_ids(response.text)

    def has_any_ac(
        self, module_id: int, activity_id: int | None = None, limit: int = 12
    ) -> tuple[bool, str]:
        """检查历史提交中是否出现过 AC。

        Args:
            module_id: 题目模块 ID。
            activity_id: 活动 ID；``None`` 时自动解析。
            limit: 最多检查的历史提交数。

        Returns:
            ``(是否曾 AC, 说明文本)``。
        """
        if activity_id is None:
            activity_id = self.resolve_activity_id(module_id)
        if activity_id is None:
            return False, ""
        submit_ids: list[int] = self.get_submit_ids(activity_id)
        for submit_id in submit_ids[:limit]:
            try:
                consequence: Consequence = self.fetch_result(activity_id, submit_id)
            except MoodleError:
                continue
            if consequence.is_ac:
                return True, "AC: Accepted"
        return False, ""

    def submit(
        self, activity_id: int, code: str, language: str = "gcc"
    ) -> int | None:
        """提交代码并返回最新提交 ID。

        Args:
            activity_id: 活动 ID。
            code: C 代码。
            language: 语言标识。

        Returns:
            最新提交 ID；读取不到时返回 ``None``。

        Raises:
            SubmitError: 网站拒绝提交时抛出。
        """
        response: requests.Response = self._post_sync(
            "mod/programming/submit.php",
            {
                "a": str(activity_id),
                "code": code,
                "language": language,
                "MAX_FILE_SIZE": "65536",
                "action": "Submit",
            },
            60.0,
        )
        accepted: bool = (
            "Submit Success" in response.text
            or "提交成功" in response.text
            or "View Results" in response.text
        )
        if not accepted:
            snippet: str = " ".join(
                parsers.clean_text(
                    (response.text or "").replace("<", " <")
                ).split()
            )[:300]
            raise SubmitError(
                "提交没有被网站接受。可能原因：题目已关闭、代码为空或登录已过期。"
                f" 页面提示：{snippet or '无'}"
            )
        submit_ids: list[int] = self.get_submit_ids(activity_id)
        return submit_ids[0] if submit_ids else None

    def fetch_result(
        self, activity_id: int, submit_id: int | None = None
    ) -> Consequence:
        """读取一次判题结果页面。

        Args:
            activity_id: 活动 ID。
            submit_id: 提交 ID。

        Returns:
            判题结果。
        """
        params: dict[str, object] = {"a": activity_id}
        if submit_id is not None:
            params["submitid"] = submit_id
        response: requests.Response = self._get_sync(
            "mod/programming/result.php", **params
        )
        return parsers.parse_consequence(response.text, submit_id=submit_id)

    def poll_consequence(
        self,
        activity_id: int,
        submit_id: int | None = None,
        timeout: float = 150.0,
        interval: float = 2.0,
    ) -> Consequence:
        """轮询判题结果直到完成或超时。

        Args:
            activity_id: 活动 ID。
            submit_id: 提交 ID。
            timeout: 最长等待秒数。
            interval: 轮询间隔秒数。

        Returns:
            最后一次解析到的判题结果。
        """
        params: dict[str, object] = {"a": activity_id}
        if submit_id is not None:
            params["submitid"] = submit_id

        deadline: float = time.monotonic() + timeout
        last: Consequence = _empty_consequence(submit_id)
        while time.monotonic() < deadline:
            try:
                response: requests.Response = self._get_sync(
                    "mod/programming/result.php", **params
                )
            except MoodleError:
                time.sleep(interval)
                continue

            last = parsers.parse_consequence(response.text, submit_id=None)
            page_submit_id: int | None = last.submit_id
            # 忽略仍显示旧提交的缓存页面。
            if (
                submit_id is not None
                and page_submit_id is not None
                and page_submit_id != submit_id
            ):
                time.sleep(interval)
                continue
            if page_submit_id is None:
                last = last._replace(submit_id=submit_id)
            if parsers.result_is_terminal(response.text, last):
                return last
            time.sleep(interval)
        return last


def get_consequence(
    site: MoodleSite,
    activity_id: int,
    submit_id: int | None = None,
    timeout: float = 150.0,
) -> Consequence:
    """获取一次提交的完整判题结果（保持原项目要求的函数形态）。

    Args:
        site: 课程平台客户端。
        activity_id: 活动 ID。
        submit_id: 提交 ID。
        timeout: 最长等待秒数。

    Returns:
        判题结果。
    """
    return site.poll_consequence(activity_id, submit_id, timeout=timeout)
