# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: client.py
# 主要用途: icourse163 RPC 与登录 HTTP 客户端。
# 文件版本: 4.6.0
"""icourse163.org HTTP 客户端。

登录使用站点「邮箱登录」表单对应的接口
``/passport/reg/icourseLogin.do``（username + passwd），
其余数据通过 ``/web/j/*.rpc`` 接口获取，csrfKey 取自 NTESSTUDYSI Cookie。
"""

from __future__ import annotations

import base64
import html as html_lib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests
from requests.cookies import RequestsCookieJar

from .config import (
    BASE_URL,
    BIFROST_RPC_BASE,
    DEFAULT_HEADERS,
    LOGIN_ENDPOINT,
    LOGIN_PAGE,
    MAX_RETRIES,
    PAGE_SIZE,
    REQUEST_TIMEOUT,
    RPC_BASE,
)

log = logging.getLogger(__name__)


class MoocError(Exception):
    """本工具所有可预期错误的基类。"""


class AuthError(MoocError):
    """未登录或登录态失效。"""


class ApiError(MoocError):
    """接口返回业务错误。"""


class NetworkError(MoocError):
    """网络请求失败。"""


class LoginMethodError(AuthError):
    """账号类型与当前登录接口不匹配，应改用浏览器登录。"""


@dataclass(frozen=True)
class LoginAttempt:
    ok: bool
    redirect: str = ""
    error_code: str = ""
    message: str = ""
    method_error: bool = False


_CREDENTIAL_HINTS = (
    "密码错误",
    "密码不正确",
    "账号或密码错误",
    "帐号或密码错误",
    "账号不存在",
    "帐号不存在",
    "用户不存在",
)
_METHOD_HINTS = (
    "验证码",
    "captcha",
    "网易通行证",
    "爱课堂",
    "爱课程账号",
    "请使用",
    "扫码登录",
    "手机号登录",
)


def parse_login_response(
    status: int,
    headers: dict[str, str],
    body: str,
    cookies: Any = None,
) -> LoginAttempt:
    """把旧版登录接口的各种返回归一化。

    旧接口可能返回 3xx、200 JSON、200 HTML、甚至 200 空 body + Set-Cookie。
    不能再把“非 3xx”一律当作失败。
    """
    location = str(headers.get("Location") or "")
    if status in (301, 302, 303, 307, 308):
        if "errorCode=" in location:
            code = location.split("errorCode=", 1)[1].split("&", 1)[0]
            return LoginAttempt(
                False,
                error_code=code,
                message="邮箱或密码错误。" if code == "-1" else f"登录失败（errorCode={code}）。",
            )
        return LoginAttempt(True, redirect=location)

    text = body or ""
    message = ""
    code = ""
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            raw_code = payload.get("code")
            if raw_code is None:
                raw_code = payload.get("errorCode")
            code = "" if raw_code is None else str(raw_code)
            message = str(
                payload.get("message")
                or payload.get("msg")
                or payload.get("error")
                or ""
            )
    except (ValueError, TypeError):
        pass

    plain = html_lib.unescape(re.sub(r"<[^>]+>", " ", text))
    haystack = f"{message} {plain}"
    has_session = False
    try:
        has_session = bool(cookies and cookies.get("STUDY_SESS"))
    except Exception:
        has_session = False

    if any(hint in haystack for hint in _CREDENTIAL_HINTS) or "errorCode=-1" in text:
        return LoginAttempt(False, message=message or "邮箱或密码错误。")

    if any(hint.lower() in haystack.lower() for hint in _METHOD_HINTS):
        return LoginAttempt(
            False,
            message=message or "该账号需要使用浏览器登录（验证码/账号类型不匹配）。",
            method_error=True,
        )

    if code in ("0", "200") or "登录成功" in haystack or has_session:
        return LoginAttempt(True, redirect=location)

    if status == 200:
        return LoginAttempt(
            False,
            message=message
            or "旧版爱课程登录接口返回 HTTP 200（非跳转），登录方式可能已变更。",
            method_error=True,
        )
    return LoginAttempt(
        False,
        message=message or f"登录失败（HTTP {status}）。",
    )


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _pick(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, "", []):
            return value
    return default


class MoocClient:
    """带上登录态的会话封装。"""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        if not self.session.headers.get("User-Agent"):
            self.session.headers.update(DEFAULT_HEADERS)
        self._logged_in = False
        self._member_id_cache: int | None = None

    # ------------------------------------------------------------------ 基础
    @classmethod
    def from_cookie_jar(cls, jar: RequestsCookieJar) -> "MoocClient":
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)
        session.cookies.update(jar)
        return cls(session)

    def _cookie(self, name: str) -> str | None:
        """兼容同名多域 Cookie（如 www./.icourse163.org）。

        requests 的 ``cookies.get`` 在存在同名 Cookie 时会抛
        CookieConflictError；这里按迭代取值，避免登录/资料解析失败。
        """
        for cookie in self.session.cookies:
            if cookie.name == name:
                return cookie.value
        return None

    @property
    def csrf_key(self) -> str:
        return self._cookie("NTESSTUDYSI") or ""

    def _bootstrap(self) -> None:
        """访问登录页，拿到 NTESSTUDYSI / EDUWEBDEVICE 等初始 Cookie。"""
        if self.csrf_key:
            return
        r = self._request("GET", LOGIN_PAGE)
        if not self.csrf_key:
            # 某些情况下登录页不设 Cookie，退回到首页
            self._request("GET", BASE_URL + "/")
        log.debug("bootstrap cookies: %s", list(self.session.cookies.keys()))

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.session.request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                log.warning("请求失败（第 %d 次）：%s", attempt, exc)
                if attempt < MAX_RETRIES:
                    time.sleep(1.5 * attempt)
                continue
            if response.status_code >= 500 and attempt < MAX_RETRIES:
                last_error = NetworkError(f"HTTP {response.status_code}")
                time.sleep(1.5 * attempt)
                continue
            return response
        raise NetworkError(f"网络请求失败：{last_error}") from last_error

    # ------------------------------------------------------------------ RPC
    def _rpc(
        self,
        method: str,
        data: dict[str, Any] | None = None,
        *,
        base: str | None = None,
    ) -> Any:
        if not self.csrf_key:
            self._bootstrap()
        url = (base or RPC_BASE) + method
        response = self._request(
            "POST",
            url,
            params={"csrfKey": self.csrf_key},
            data=data or {},
            headers={"Referer": BASE_URL + "/", "X-Requested-With": "XMLHttpRequest"},
        )
        return self._decode_rpc_response(response, method)

    def _decode_rpc_response(self, response: requests.Response, method: str) -> Any:
        if response.status_code in (401, 403):
            raise AuthError("登录状态已失效，请重新登录中国大学慕课。")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiError(
                f"接口返回了非 JSON 内容（HTTP {response.status_code}）：{method}"
            ) from exc

        code = payload.get("code")
        message = str(payload.get("message") or "")
        if code == 0:
            return payload.get("result")
        if "not_auth" in message or "not login" in message.lower():
            raise AuthError("登录状态已失效，请重新登录中国大学慕课。")
        raise ApiError(f"接口 {method} 出错：[{code}] {message}")

    def _bifrost_rpc(self, method: str, data: dict[str, Any] | None = None) -> Any:
        return self._rpc(method, data, base=BIFROST_RPC_BASE)

    # ------------------------------------------------------------------ 登录
    def login(
        self,
        email: str,
        password: str,
        *,
        account_type: str = "icourse",
    ) -> dict[str, Any]:
        """使用爱课程账号 + 密码登录；网易/手机号请用浏览器登录。"""
        if not email or not password:
            raise AuthError("账号和密码不能为空。")
        if str(account_type).lower() in (
            "mail",
            "phone",
            "netease",
            "netease_phone",
        ):
            raise LoginMethodError(
                "网易通行证账号请使用浏览器窗口登录"
            )

        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._bootstrap()

        payload = {
            "returnUrl": _b64(BASE_URL + "/"),
            "failUrl": _b64(LOGIN_PAGE),
            "saveLogin": "true",
            "oauthType": "",
            "username": email,
            "passwd": password,
        }
        log.debug("POST %s", LOGIN_ENDPOINT)
        response = self._request(
            "POST",
            LOGIN_ENDPOINT,
            data=payload,
            allow_redirects=False,
            headers={"Referer": LOGIN_PAGE, "Origin": BASE_URL},
        )

        try:
            body = response.text
        except Exception:
            body = ""
        attempt = parse_login_response(
            response.status_code,
            dict(response.headers),
            body,
            self.session.cookies,
        )
        if not attempt.ok:
            if attempt.method_error:
                raise LoginMethodError(attempt.message)
            raise AuthError(attempt.message or "登录失败。")

        if attempt.redirect:
            self._request("GET", urljoin(BASE_URL, attempt.redirect))

        return self._finish_login()

    def _finish_login(self) -> dict[str, Any]:
        if not self.csrf_key:
            self._bootstrap()
        if not self.csrf_key:
            raise AuthError("登录后未能取得会话 Cookie（NTESSTUDYSI）。")
        try:
            member = self.get_member()
        except AuthError:
            raise LoginMethodError(
                "登录未生效：该账号可能不是爱课程邮箱账号，"
                "请使用浏览器窗口登录。"
            ) from None
        self._logged_in = True
        return member

    # ------------------------------------------------------------------ 数据
    def _identity(self) -> tuple[int | None, str | None]:
        """从 STUDY_INFO Cookie 中解析 (uid, 邮箱)。"""
        raw = self._cookie("STUDY_INFO")
        if not raw:
            return None, None
        value = raw.strip().strip('"')
        parts = value.split("|")
        email = parts[0].strip() if parts else None
        uid = None
        if len(parts) >= 3:
            try:
                uid = int(parts[2])
            except ValueError:
                uid = None
        return uid, email or None

    @property
    def member_id(self) -> int | None:
        uid = self._identity()[0]
        if uid:
            self._member_id_cache = uid
        return uid or self._member_id_cache

    def _fetch_nickname(self) -> str:
        try:
            response = self._request("GET", BASE_URL + "/")
            match = re.search(r'nickName["\']?\s*:\s*["\']([^"\']+)', response.text)
            if match:
                return match.group(1)
        except MoocError:
            pass
        return ""

    def get_member(self) -> dict[str, Any]:
        """当前登录用户信息；未登录时抛 AuthError。

        memberBean.getMocMember.rpc 在未登录时返回 not_auth，登录后即使缺少参数
        也会返回 code 0，因此用它作为登录态校验，用户信息再从 Cookie 中补齐。
        """
        result = self._rpc("memberBean.getMocMember.rpc")

        member: dict[str, Any] = {}
        if isinstance(result, dict):
            member.update(result)

        uid, email = self._identity()
        if uid:
            self._member_id_cache = uid
            member.setdefault("id", uid)
        elif member.get("id"):
            try:
                self._member_id_cache = int(member["id"])
            except (TypeError, ValueError):
                pass
        if email:
            member.setdefault("loginId", email)
            member.setdefault("email", email)
        if not member.get("id") and not member.get("loginId"):
            raise AuthError("无法从登录 Cookie 中解析用户信息，请重新登录。")
        if not member.get("nickName"):
            nickname = self._fetch_nickname()
            if nickname:
                member["nickName"] = nickname
        return member

    def is_logged_in(self) -> bool:
        try:
            self.get_member()
            return True
        except MoocError:
            return False

    # ------------------------------------------------------------------ 用户资料
    def get_profile(self) -> dict[str, Any]:
        uid = self.member_id
        if not uid:
            raise AuthError("登录 Cookie 中缺少 uid，请重新登录。")
        result = self._rpc(
            "memberBean.getMocMemberPersonalDtoById.rpc", {"memberId": uid}
        )
        return result if isinstance(result, dict) else {}

    def school_id(self) -> int | None:
        profile = self.get_profile()
        candidates = [
            profile.get("schoolId"),
            (profile.get("webUser") or {}).get("schoolId"),
            (profile.get("memberDto") or {}).get("schoolId"),
            (profile.get("schoolPanel") or {}).get("id"),
        ]
        for value in candidates:
            try:
                if value not in (None, "", 0, "0"):
                    return int(value)
            except (TypeError, ValueError):
                continue
        return None

    def support_spoc(self) -> bool | None:
        value = self.get_profile().get("supportSpoc")
        return None if value is None else bool(value)

    # ------------------------------------------------------------------ 课程
    @staticmethod
    def _course_key(item: dict[str, Any]) -> Any:
        term = _pick(item, "termId", "term_id", "id")
        if not term:
            term = _pick(item.get("termDto") or {}, "id", "termId", "term_id")
        course = _pick(item, "courseId", "course_id")
        if not course:
            course = _pick(item.get("courseDto") or {}, "id", "courseId", "course_id")
        return term or course or repr(sorted(item.items()))

    def get_spoc_courses(self, school_id: int | str | None = None) -> list[dict[str, Any]]:
        """SPOC/学校云课程列表。

        正确数据源是 ``learnerCourseRpcBean.getMyLearnedCoursePanelList.rpc``
        （type=30, courseType=2）；``mm-bifrost`` 仅作为兜底。
        """
        items = self._get_spoc_panel_courses(school_id)
        if items:
            return items
        return self._get_spoc_bifrost_courses(school_id)

    def _get_spoc_panel_courses(
        self, school_id: int | str | None = None
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while page <= 50:
            result = self._rpc(
                "learnerCourseRpcBean.getMyLearnedCoursePanelList.rpc",
                {"type": 30, "p": page, "psize": 50, "courseType": 2},
            )
            if not isinstance(result, dict):
                break
            batch = result.get("result") or result.get("list") or []
            if not isinstance(batch, list) or not batch:
                break
            pagination = result.get("pagination") or {}
            for item in batch:
                if not isinstance(item, dict):
                    continue
                item = dict(item)
                item["_spoc"] = True
                if school_id:
                    sid = (
                        (item.get("schoolPanel") or {}).get("id")
                        or (item.get("termPanel") or {}).get("schoolId")
                    )
                    try:
                        if sid and int(sid) != int(school_id):
                            continue
                    except (TypeError, ValueError):
                        pass
                items.append(item)
            total_pages = int(
                pagination.get("totlePageCount")
                or pagination.get("totalPageCount")
                or 1
            )
            if page >= total_pages:
                break
            page += 1
        return items

    def _get_spoc_bifrost_courses(
        self, school_id: int | str | None = None
    ) -> list[dict[str, Any]]:
        profile = self.get_profile()
        if school_id in (None, ""):
            school_id = profile.get("schoolId")
        if school_id in (None, "", 0, "0"):
            return []
        if profile.get("supportSpoc") is False:
            return []

        try:
            count = self._bifrost_rpc(
                "mocCourseBean.getCourseCount.rpc", {"schoolId": int(school_id)}
            )
            if isinstance(count, int) and count <= 0:
                return []
        except MoocError:
            pass

        items: list[dict[str, Any]] = []
        page = 1
        while page <= 50:
            result = self._bifrost_rpc(
                "mocCourseBean.getCourseList.rpc",
                {
                    "pageIndex": page,
                    "pageSize": PAGE_SIZE,
                    "schoolId": int(school_id),
                },
            )
            if isinstance(result, list):
                batch = result
                total_pages = 1
            elif isinstance(result, dict):
                batch = (
                    result.get("list")
                    or result.get("result")
                    or result.get("courseList")
                    or []
                )
                query = result.get("query") or {}
                total_pages = int(
                    query.get("totlePageCount")
                    or query.get("totalPageCount")
                    or 1
                )
            else:
                break
            if not isinstance(batch, list) or not batch:
                break
            for item in batch:
                if not isinstance(item, dict):
                    continue
                item = dict(item)
                item["_spoc"] = True
                items.append(item)
            if page >= total_pages:
                break
            page += 1
        return items

    def get_enrolled_courses(
        self,
        *,
        include_spoc: bool = True,
        spoc_school_id: int | str | None = None,
    ) -> list[dict[str, Any]]:
        """返回我加入的全部课程（MOOC + 可选 SPOC/其他学习记录）。"""
        uid = self.member_id
        if not uid:
            raise AuthError("登录 Cookie 中缺少 uid，请重新登录。")

        methods = (
            "learnerCourseRpcBean.getBothLearnedCoursePagination.rpc",
            "learnerCourseRpcBean.getOtherLearnedCoursePagination.rpc",
        )
        items: list[dict[str, Any]] = []
        seen: dict[Any, dict[str, Any]] = {}

        def merge(item: dict[str, Any]) -> None:
            key = self._course_key(item)
            existing = seen.get(key)
            if existing is None:
                seen[key] = item
                items.append(item)
            else:
                # 同一门课可能同时出现在 MOOC/SPOC 列表：合并缺失字段，
                # 并保留 SPOC 标记。
                for field, value in item.items():
                    if existing.get(field) in (None, "", []) or field == "_spoc":
                        existing[field] = value

        for method in methods:
            page = 1
            while page <= 50:
                result = self._rpc(
                    method,
                    {"uid": uid, "pageIndex": page, "pageSize": PAGE_SIZE},
                )
                if not isinstance(result, dict):
                    break
                batch = result.get("list") or result.get("result") or []
                if not isinstance(batch, list) or not batch:
                    break
                for item in batch:
                    if isinstance(item, dict):
                        merge(item)
                query = result.get("query") or {}
                total_pages = query.get("totlePageCount") or query.get("totalPageCount") or 1
                if page >= int(total_pages):
                    break
                page += 1

        if include_spoc:
            try:
                for item in self.get_spoc_courses(spoc_school_id):
                    merge(item)
            except MoocError as exc:
                log.debug("SPOC 课程获取失败：%s", exc)
        return items

    def get_term(self, term_id: int) -> dict[str, Any]:
        """课程学期详情：章节 → 小节 → 单元，含测验/作业/考试。

        getMocTermDto 返回完整结构（含未发布内容），但不含个人学习状态；
        getLastLearnedMocTermDto 返回已发布内容 + 个人 viewStatus，需要合并。
        """
        term = self._rpc(
            "courseBean.getMocTermDto.rpc",
            {"termId": int(term_id), "isDraft": 0, "excludeUnrelease": 0},
        )
        if not isinstance(term, dict):
            raise ApiError(f"课程 {term_id} 返回格式异常。")

        try:
            learned = self._rpc(
                "courseBean.getLastLearnedMocTermDto.rpc", {"termId": int(term_id)}
            )
        except ApiError:
            learned = None
        if isinstance(learned, dict) and isinstance(learned.get("mocTermDto"), dict):
            merge_learn_status(term, learned["mocTermDto"])
            term["_lastLearnUnitId"] = learned.get("lastLearnUnitId")
        return term


_LEARN_FIELDS = ("viewStatus", "completePercent", "learnTime", "testScore")
_TEST_FIELDS = ("userScore", "usedTryCount", "submitTestCount", "submitCount")


def merge_learn_status(term: dict[str, Any], learned: dict[str, Any]) -> None:
    """把个人学习状态（viewStatus 等）从 learned 合并进完整课程结构。"""
    index: dict[tuple[str, Any], dict[str, Any]] = {}

    def build(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("id"), int):
                index.setdefault(("id", node["id"]), node)
            if node.get("contentId") is not None:
                index.setdefault(("content", node["contentId"]), node)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    build(value)
        elif isinstance(node, list):
            for value in node:
                build(value)

    def apply(node: Any) -> None:
        if isinstance(node, dict):
            src = None
            if isinstance(node.get("id"), int):
                src = index.get(("id", node["id"]))
            if src is None and node.get("contentId") is not None:
                src = index.get(("content", node["contentId"]))
            if src is not None:
                for key in _LEARN_FIELDS:
                    if src.get(key) is not None:
                        node[key] = src[key]
                for key in ("test", "exam"):
                    learned_obj = src.get(key)
                    target_obj = node.get(key)
                    if isinstance(learned_obj, dict) and isinstance(target_obj, dict):
                        for field in _TEST_FIELDS:
                            if learned_obj.get(field) is not None:
                                target_obj[field] = learned_obj[field]
                for field in _TEST_FIELDS:
                    if src.get(field) is not None and field in node:
                        node[field] = src[field]
            for value in node.values():
                if isinstance(value, (dict, list)):
                    apply(value)
        elif isinstance(node, list):
            for value in node:
                apply(value)

    build(learned)
    apply(term)
