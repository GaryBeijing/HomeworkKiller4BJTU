# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 文件名: client.py
# 主要用途: 封装高铁答题系统的验证码、登录与考试接口。
# 文件版本: 1.0.0
"""高铁答题系统 API 客户端。

接口地址与原版保持一致；所有网络请求都使用显式超时，并在失败时抛出
:class:`HsrApiError`，由上层转换为用户可读提示。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Final

from .aes import aes_ecb_encrypt_b64
from .captcha import solve_offset

__version__ = "1.0.0"
__all__ = ["BASE_URL", "HsrApiError", "HsrClient"]

BASE_URL: Final[str] = "http://59.64.5.158/prod-api"


class HsrApiError(RuntimeError):
    """高铁接口调用异常。"""

    def __init__(self, message: str, payload: dict[str, Any] | None = None) -> None:
        """初始化异常。

        Args:
            message: 面向用户的错误信息。
            payload: 服务端返回的原始数据，便于排查。
        """
        super().__init__(message)
        self.payload: dict[str, Any] = payload or {}


class HsrClient:
    """高铁答题系统客户端。

    一个实例对应一次登录会话；``login`` 成功后自动持有 Bearer Token。
    """

    def __init__(self, timeout: float = 40.0) -> None:
        """初始化客户端。

        Args:
            timeout: 单次网络请求超时秒数。
        """
        self._timeout: float = float(timeout)
        self._token: str | None = None

    @property
    def token(self) -> str | None:
        """返回当前登录 Token。

        Returns:
            Token 字符串；未登录时为 ``None``。
        """
        return self._token

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """发送一次 JSON 请求并解析响应。

        Args:
            method: HTTP 方法，如 ``"GET"``、``"POST"``。
            path: 相对 ``BASE_URL`` 的路径。
            payload: 请求体；``None`` 表示无请求体。

        Returns:
            解析后的 JSON 对象。

        Raises:
            HsrApiError: 网络失败、HTTP 错误或响应无法解析时抛出。
        """
        data: bytes | None = None
        headers: dict[str, str] = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json;charset=utf-8"
        if self._token:
            headers["Authorization"] = "Bearer " + self._token

        request: urllib.request.Request = urllib.request.Request(
            BASE_URL + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body: str = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            error_body: str = exc.read().decode("utf-8", "replace")
            parsed_error: dict[str, Any] | None = None
            try:
                candidate: Any = json.loads(error_body)
                if isinstance(candidate, dict):
                    parsed_error = candidate
            except json.JSONDecodeError:
                parsed_error = None
            message: str = (
                str(parsed_error.get("msg"))
                if parsed_error and parsed_error.get("msg")
                else "接口返回 HTTP %s" % exc.code
            )
            raise HsrApiError(message, parsed_error) from exc
        except urllib.error.URLError as exc:
            raise HsrApiError("网络请求失败，请检查网络连接: %s" % exc.reason) from exc
        except TimeoutError as exc:
            raise HsrApiError("网络请求超时，请稍后重试") from exc

        try:
            result: Any = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HsrApiError("接口响应不是合法 JSON") from exc
        if not isinstance(result, dict):
            raise HsrApiError("接口响应格式异常")
        return result

    def _solve_captcha(self, max_try: int = 4) -> str:
        """自动完成滑块验证码并返回登录所需的校验串。

        Args:
            max_try: 最大尝试次数。

        Returns:
            登录接口使用的 ``code`` 参数。

        Raises:
            HsrApiError: 多次尝试仍未通过时抛出。
        """
        last_payload: dict[str, Any] | None = None
        for attempt in range(max_try):
            # 步骤 1：向服务端申请一张拼图验证码。
            captcha_response: dict[str, Any] = self._request(
                "POST", "/captcha/get", {"captchaType": "blockPuzzle"}
            )
            if captcha_response.get("repCode") != "0000":
                last_payload = captcha_response
                time.sleep(0.5)
                continue
            captcha_data: Any = captcha_response.get("repData")
            if not isinstance(captcha_data, dict):
                last_payload = captcha_response
                time.sleep(0.5)
                continue

            # 步骤 2：本地计算拼图块偏移。
            match = solve_offset(
                str(captcha_data.get("originalImageBase64") or ""),
                str(captcha_data.get("jigsawImageBase64") or ""),
            )
            point_json: str = json.dumps(
                {"x": int(match.x), "y": 5}, separators=(",", ":")
            )
            secret_key: str = str(captcha_data.get("secretKey") or "")
            encrypted_point: str = aes_ecb_encrypt_b64(
                point_json.encode("utf-8"), secret_key
            )

            # 步骤 3：提交坐标校验。
            check_response: dict[str, Any] = self._request(
                "POST",
                "/captcha/check",
                {
                    "captchaType": "blockPuzzle",
                    "pointJson": encrypted_point,
                    "token": captcha_data.get("token"),
                },
            )
            if check_response.get("repCode") == "0000":
                verification: str = aes_ecb_encrypt_b64(
                    (str(captcha_data.get("token")) + "---" + point_json).encode("utf-8"),
                    secret_key,
                )
                return verification
            last_payload = check_response
            time.sleep(0.4)
        raise HsrApiError("验证码多次未通过", last_payload)

    def login(self, username: str, password: str) -> str:
        """登录并保存 Token。

        Args:
            username: 学号/账号。
            password: 密码。

        Returns:
            登录成功后的 Token。

        Raises:
            HsrApiError: 验证码或登录失败时抛出。
        """
        code: str = self._solve_captcha()
        response: dict[str, Any] = self._request(
            "POST",
            "/login",
            {
                "username": username,
                "password": password,
                "code": code,
                "uuid": "",
            },
        )
        token: Any = response.get("token")
        if not token:
            raise HsrApiError(
                "登录失败: %s" % (response.get("msg") or "未返回 Token"), response
            )
        self._token = str(token)
        return self._token

    def exam_list(self) -> dict[str, Any]:
        """读取当前账号的考试列表。

        Returns:
            分页对象（含 ``records`` 或 ``rows``）。

        Raises:
            HsrApiError: 未登录或接口失败时抛出。
        """
        query: str = urllib.parse.urlencode({"pageNumber": 1, "pageSize": 100})
        response: dict[str, Any] = self._request("GET", "/exam/my?" + query)
        # 该接口在原版中直接返回裸分页对象，不带 code 字段。
        if "records" in response or "rows" in response:
            return response
        if response.get("code") == 200:
            return response
        raise HsrApiError(
            "读取考试列表失败: %s" % (response.get("msg") or response.get("code")),
            response,
        )

    def start_precheck(self, exam_id: int) -> dict[str, Any]:
        """开始考试前的预检。

        Args:
            exam_id: 考试 ID。

        Returns:
            预检响应数据。

        Raises:
            HsrApiError: 预检未通过时抛出。
        """
        response: dict[str, Any] = self._request(
            "POST", "/exam/startPreCheck/%s" % exam_id, {}
        )
        if response.get("code") != 200:
            raise HsrApiError(
                "预检失败: %s" % (response.get("msg") or response.get("code")),
                response,
            )
        return response

    def start_exam(self, exam_id: int) -> dict[str, Any]:
        """开始考试并生成个人试卷（会消耗一次作答机会）。

        Args:
            exam_id: 考试 ID。

        Returns:
            试卷数据。

        Raises:
            HsrApiError: 开始考试失败时抛出。
        """
        response: dict[str, Any] = self._request(
            "POST", "/exam/startExam/%s" % exam_id, {}
        )
        if response.get("code") != 200:
            raise HsrApiError(
                "开始考试失败: %s" % (response.get("msg") or response.get("code")),
                response,
            )
        data: Any = response.get("data")
        if not isinstance(data, dict):
            raise HsrApiError("试卷数据格式异常", response)
        return data

    def save_exam(self, payload: dict[str, Any]) -> dict[str, Any]:
        """保存试卷（保留原版接口能力）。

        Args:
            payload: 试卷提交结构。

        Returns:
            原始响应。
        """
        return self._request("POST", "/exam/save", payload)

    def commit_exam(self, payload: dict[str, Any]) -> dict[str, Any]:
        """提交试卷。

        Args:
            payload: 试卷提交结构。

        Returns:
            原始响应。
        """
        return self._request("POST", "/exam/commit", payload)

    def detail_answer(self, personal_exam_id: int) -> dict[str, Any]:
        """读取个人答卷详情（保留原版接口能力）。

        Args:
            personal_exam_id: 个人试卷 ID。

        Returns:
            答卷详情数据。

        Raises:
            HsrApiError: 接口失败时抛出。
        """
        response: dict[str, Any] = self._request(
            "GET", "/exam/detailAnswer?id=%s" % personal_exam_id
        )
        if response.get("code") != 200:
            raise HsrApiError(
                "读取答卷详情失败: %s" % (response.get("msg") or response.get("code")),
                response,
            )
        data: Any = response.get("data")
        return data if isinstance(data, dict) else {}
