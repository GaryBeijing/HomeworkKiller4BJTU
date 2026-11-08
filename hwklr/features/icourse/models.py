# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: models.py
# 主要用途: 把 icourse163 接口 JSON 转换为课程/任务模型与完成状态（已移除 CLI 课程编号）。
# 文件版本: 4.0.0
"""把接口返回的 JSON 转换成课程 / 任务模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

DONE = "done"
PENDING = "pending"
UPCOMING = "upcoming"
OVERDUE = "overdue"

STATUS_LABELS = {
    DONE: "已完成",
    PENDING: "未完成",
    UPCOMING: "未开始",
    OVERDUE: "已逾期",
}

UNIT_KIND_LABELS = {
    1: "视频",
    2: "测验",
    3: "文档",
    4: "富文本",
    5: "随堂测验",
    6: "讨论",
    7: "作业",
    8: "考试",
    9: "直播",
}

QUIZ_KIND = "测验"
HOMEWORK_KIND = "作业"
EXAM_KIND = "考试"
DOCUMENT_KIND = "文档"


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ms_to_dt(value: Any) -> datetime | None:
    ms = _int_or_none(value)
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone()
    except (OverflowError, OSError, ValueError):
        return None


def _pick(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, "", []):
            return value
    return default


def _now_ms() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp() * 1000)


def completion_ratio(value: Any) -> float | None:
    """把 ``completePercent`` 归一化到 0..1。

    站点当前返回的是小数比例（``1.0`` 表示 100%、``0.701`` 表示 70.1%），
    旧接口/缓存里也可能出现 0..100 的百分数；两种都要兼容。
    """
    percent = _float_or_none(value)
    if percent is None:
        return None
    if percent <= 0:
        return 0.0
    if percent <= 1.0:
        return percent
    return percent / 100.0


def _is_done(
    state: dict[str, Any] | None,
    test: dict[str, Any] | None = None,
    exam: dict[str, Any] | None = None,
) -> bool:
    """综合 completePercent / 作答记录判断任务是否已完成。

    真实 learned 数据里 ``viewStatus=5`` 只表示「访问过」：70% 的视频也是 5，
    不能单独当作完成；``viewStatus == 1`` 只作为旧接口的兼容兜底。
    """
    if state:
        view_status = _int_or_none(state.get("viewStatus"))
        if view_status == 1:
            return True
        ratio = completion_ratio(state.get("completePercent"))
        if ratio is not None and ratio >= 1.0:
            return True
        # 文档（课件）没有播放进度：站点打开文档页后会写 viewStatus=5，
        # 浏览器端即显示完成；视频的 viewStatus=5 只表示“访问过”，
        # 仍有 completePercent 区分 70%/100%，不能套用这条规则。
        if (
            _int_or_none(state.get("contentType")) == 3
            and view_status == 5
        ):
            return True
    # 注意：submitTestCount / usedTryCount 在匿名响应里也可能是全站统计值，
    # 不能作为「本人已完成」的依据；只认本人的 userScore。
    for obj in (test, exam):
        if obj and obj.get("userScore") is not None:
            return True
    return False


def _classify_status(
    done: bool, release_ms: Any, deadline_ms: Any, now_ms: int
) -> str:
    if done:
        return DONE
    release = _int_or_none(release_ms)
    if release and release > now_ms:
        return UPCOMING
    deadline = _int_or_none(deadline_ms)
    if deadline and deadline < now_ms:
        return OVERDUE
    return PENDING


@dataclass
class Task:
    chapter: str
    lesson: str
    name: str
    kind: str
    status: str
    score: float | None = None
    total_score: float | None = None
    deadline: datetime | None = None
    release: datetime | None = None
    content_id: int | None = None
    unit_id: int | None = None
    lesson_id: int | None = None
    chapter_id: int | None = None
    term_id: int | None = None
    content_type: int | None = None
    test_id: int | None = None
    key: str = ""
    _sort: tuple = field(default=(0.0, 0.0, 0.0, 0), repr=False, compare=False)

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter": self.chapter,
            "lesson": self.lesson,
            "name": self.name,
            "type": self.kind,
            "status": self.status,
            "status_label": self.status_label,
            "score": self.score,
            "total_score": self.total_score,
            "deadline": self.deadline.isoformat(timespec="minutes") if self.deadline else None,
            "release": self.release.isoformat(timespec="minutes") if self.release else None,
            "content_id": self.content_id,
            "unit_id": self.unit_id,
            "lesson_id": self.lesson_id,
            "chapter_id": self.chapter_id,
            "term_id": self.term_id,
            "content_type": self.content_type,
            "test_id": self.test_id,
            "key": self.key,
        }


@dataclass
class Course:
    term_id: int
    course_id: int | None = None
    name: str = ""
    school: str = ""
    school_short_name: str = ""
    is_spoc: bool = False
    start: datetime | None = None
    end: datetime | None = None
    tasks: list[Task] = field(default_factory=list)

    @property
    def learn_url(self) -> str | None:
        if not (self.school_short_name and self.course_id):
            return None
        prefix = "spoc/learn" if self.is_spoc else "learn"
        return (
            f"https://www.icourse163.org/{prefix}/{self.school_short_name}-"
            f"{self.course_id}?tid={self.term_id}"
        )

    def status_counts(self) -> dict[str, int]:
        counts = {DONE: 0, PENDING: 0, UPCOMING: 0, OVERDUE: 0}
        for task in self.tasks:
            counts[task.status] = counts.get(task.status, 0) + 1
        counts["total"] = len(self.tasks)
        return counts

    @property
    def pending_count(self) -> int:
        counts = self.status_counts()
        return counts[PENDING] + counts[OVERDUE]

    def to_dict(self, include_tasks: bool = True) -> dict[str, Any]:
        counts = self.status_counts()
        total = counts["total"]
        data = {
            "term_id": self.term_id,
            "course_id": self.course_id,
            "name": self.name,
            "school": self.school,
            "school_short_name": self.school_short_name,
            "is_spoc": self.is_spoc,
            "learn_url": self.learn_url,
            "start": self.start.isoformat(timespec="minutes") if self.start else None,
            "end": self.end.isoformat(timespec="minutes") if self.end else None,
            "summary": {
                **counts,
                "done_percent": round(counts[DONE] * 100 / total) if total else 0,
            },
        }
        if include_tasks:
            data["tasks"] = [task.to_dict() for task in self.tasks]
        return data


def _school_name(term: dict[str, Any], source: dict[str, Any] | None) -> str:
    candidates = []
    if source:
        candidates.extend(
            [
                source.get("schoolName"),
                source.get("school"),
                (source.get("schoolPanel") or {}).get("name"),
                (source.get("courseDto") or {}).get("schoolName"),
            ]
        )
    for role in ("chiefLectorDto", "chiefLector"):
        lector = term.get(role) or {}
        if isinstance(lector, dict):
            candidates.append((lector.get("schoolPanel") or {}).get("name"))
            candidates.append(lector.get("schoolName"))
    for name in candidates:
        if name:
            return str(name)
    return ""


def _task_from_test(
    *,
    chapter: str,
    lesson: str,
    name: str,
    kind: str,
    state: dict[str, Any],
    test: dict[str, Any] | None = None,
    exam: dict[str, Any] | None = None,
    sort: tuple,
    lesson_id: int | None = None,
    chapter_id: int | None = None,
    term_id: int | None = None,
) -> Task:
    info = test or exam or state
    done = _is_done(state, test=test, exam=exam)
    release = _pick(info, "releaseTime", default=state.get("releaseTime"))
    deadline = _pick(info, "deadline", default=state.get("deadline"))
    status = _classify_status(done, release, deadline, _now_ms())
    return Task(
        chapter=chapter,
        lesson=lesson,
        name=name,
        kind=kind,
        status=status,
        score=_float_or_none(info.get("userScore")),
        total_score=_float_or_none(info.get("totalScore")),
        deadline=_ms_to_dt(deadline),
        release=_ms_to_dt(release),
        content_id=_int_or_none(state.get("contentId") or info.get("id")),
        lesson_id=lesson_id,
        chapter_id=chapter_id,
        term_id=term_id,
        test_id=_int_or_none(info.get("id")),
        _sort=sort,
    )


def _is_spoc_source(source: dict[str, Any]) -> bool:
    for candidate in _source_candidates(source or {}):
        if candidate.get("_spoc") or candidate.get("isSpoc") or candidate.get("spoc"):
            return True
        course_dto = candidate.get("courseDto")
        if isinstance(course_dto, dict) and (
            course_dto.get("_spoc") or course_dto.get("isSpoc") or course_dto.get("spoc")
        ):
            return True
    return False


def build_course(term: dict[str, Any], source: dict[str, Any] | None = None) -> Course:
    """从 getMocTermDto 的返回构建课程及任务列表。"""
    term_id = _int_or_none(term.get("id")) or _int_or_none(term.get("termId")) or 0
    source_obj = source or {}
    source_course = source_obj.get("courseDto") or {}
    source_term = source_obj.get("termPanel") or {}
    source_school = source_obj.get("schoolPanel") or {}
    course = Course(
        term_id=term_id,
        course_id=_int_or_none(term.get("courseId"))
        or _int_or_none(source_term.get("courseId"))
        or _int_or_none(source_obj.get("id"))
        or _int_or_none(source_course.get("id")),
        name=str(term.get("courseName") or term.get("name") or "")
        or str(source_course.get("name") or "")
        or str(source_obj.get("name") or ""),
        school=_school_name(term, source),
        school_short_name=str(
            source_school.get("shortName")
            or _from_sources(_source_candidates(source_obj), "schoolShortName")
            or ""
        ),
        is_spoc=_is_spoc_source(source_obj),
        start=_ms_to_dt(term.get("startTime")),
        end=_ms_to_dt(term.get("endTime")),
    )

    entries: list[tuple[tuple, Task]] = []
    seq = 0
    seen: set[tuple] = set()

    def add(sort: tuple, task: Task) -> None:
        nonlocal seq
        key = (task.kind, task.content_id, task.name)
        if key in seen:
            return
        seen.add(key)
        entries.append((sort, task))
        seq += 1

    for chapter in sorted(
        term.get("chapters") or [], key=lambda c: _num(c.get("position"))
    ):
        cpos = _num(chapter.get("position"))
        cname = str(chapter.get("name") or "")

        for lesson in sorted(
            chapter.get("lessons") or [], key=lambda l: _num(l.get("position"))
        ):
            lpos = _num(lesson.get("position"))
            lname = str(lesson.get("name") or "")

            for unit in sorted(
                lesson.get("units") or [], key=lambda u: _num(u.get("position"))
            ):
                upos = _num(unit.get("position"))
                ctype = _int_or_none(unit.get("contentType")) or 0
                kind = UNIT_KIND_LABELS.get(ctype, f"其他({ctype})")
                done = _is_done(unit)
                status = _classify_status(
                    done, unit.get("releaseTime"), None, _now_ms()
                )
                task = Task(
                    chapter=cname,
                    lesson=lname,
                    name=str(unit.get("name") or kind),
                    kind=kind,
                    status=status,
                    score=_float_or_none(unit.get("testScore")),
                    content_id=_int_or_none(unit.get("contentId")),
                    unit_id=_int_or_none(unit.get("unitId") or unit.get("id")),
                    lesson_id=_int_or_none(lesson.get("id")),
                    chapter_id=_int_or_none(chapter.get("id")),
                    term_id=term_id,
                    content_type=ctype,
                    _sort=(cpos, lpos, upos, seq),
                )
                add((cpos, lpos, upos, seq), task)

            lesson_test = lesson.get("test")
            if isinstance(lesson_test, dict):
                add(
                    (cpos, lpos, 900, seq),
                    _task_from_test(
                        chapter=cname,
                        lesson=lname,
                        name=str(lesson_test.get("name") or lname),
                        kind=QUIZ_KIND,
                        state=lesson,
                        test=lesson_test,
                        sort=(cpos, lpos, 900, seq),
                        lesson_id=_int_or_none(lesson.get("id")),
                        chapter_id=_int_or_none(chapter.get("id")),
                        term_id=term_id,
                    ),
                )
            lesson_exam = lesson.get("exam")
            if isinstance(lesson_exam, dict):
                add(
                    (cpos, lpos, 901, seq),
                    _task_from_test(
                        chapter=cname,
                        lesson=lname,
                        name=str(lesson_exam.get("name") or lname),
                        kind=EXAM_KIND,
                        state=lesson,
                        exam=lesson_exam,
                        sort=(cpos, lpos, 901, seq),
                        lesson_id=_int_or_none(lesson.get("id")),
                        chapter_id=_int_or_none(chapter.get("id")),
                        term_id=term_id,
                    ),
                )

        for quiz in chapter.get("quizs") or []:
            if not isinstance(quiz, dict):
                continue
            qpos = _num(quiz.get("position")) or 950
            test = quiz.get("test") if isinstance(quiz.get("test"), dict) else {}
            add(
                (cpos, qpos, 0, seq),
                _task_from_test(
                    chapter=cname,
                    lesson="",
                    name=str(quiz.get("name") or test.get("name") or QUIZ_KIND),
                    kind=QUIZ_KIND,
                    state=quiz,
                    test=test,
                    sort=(cpos, qpos, 0, seq),
                    chapter_id=_int_or_none(chapter.get("id")),
                    term_id=term_id,
                ),
            )

        for homework in chapter.get("homeworks") or []:
            if not isinstance(homework, dict):
                continue
            hpos = _num(homework.get("position")) or 951
            test = next(
                (
                    homework[key]
                    for key in ("test", "homework")
                    if isinstance(homework.get(key), dict)
                ),
                {},
            )
            add(
                (cpos, hpos, 0, seq),
                _task_from_test(
                    chapter=cname,
                    lesson="",
                    name=str(homework.get("name") or test.get("name") or HOMEWORK_KIND),
                    kind=HOMEWORK_KIND,
                    state=homework,
                    test=test,
                    sort=(cpos, hpos, 0, seq),
                    chapter_id=_int_or_none(chapter.get("id")),
                    term_id=term_id,
                ),
            )

        chapter_exam = chapter.get("exam")
        if isinstance(chapter_exam, dict):
            add(
                (cpos, 1000, 0, seq),
                _task_from_test(
                    chapter=cname,
                    lesson="",
                    name=str(chapter_exam.get("name") or EXAM_KIND),
                    kind=EXAM_KIND,
                    state=chapter_exam,
                    exam=chapter_exam,
                    sort=(cpos, 1000, 0, seq),
                    chapter_id=_int_or_none(chapter.get("id")),
                    term_id=term_id,
                ),
            )

    for exam in term.get("exams") or []:
        if not isinstance(exam, dict):
            continue
        add(
            (10_000 + _num(exam.get("position")), 0, 0, seq),
            _task_from_test(
                chapter="",
                lesson="",
                name=str(exam.get("name") or EXAM_KIND),
                kind=EXAM_KIND,
                state=exam,
                exam=exam,
                sort=(10_000, 0, 0, seq),
                term_id=term_id,
            ),
        )

    entries.sort(key=lambda pair: pair[0])
    course.tasks = [task for _, task in entries]
    return course


def _source_candidates(source: dict[str, Any]) -> list[dict[str, Any]]:
    """课程列表接口的条目可能把字段嵌套在 term/course 等对象里。"""
    candidates = [source]
    for key in (
        "term",
        "termDto",
        "termPanel",
        "courseTerm",
        "course",
        "courseDto",
        "coursePanel",
        "schoolPanel",
        "learnedCourse",
        "mocTermDto",
    ):
        nested = source.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
            for inner_key in ("term", "course", "courseDto"):
                inner = nested.get(inner_key)
                if isinstance(inner, dict):
                    candidates.append(inner)
    return candidates


def _from_sources(sources: list[dict[str, Any]], *keys: str) -> Any:
    for source in sources:
        value = _pick(source, *keys)
        if value not in (None, "", []):
            return value
    return None


def extract_term_id(source: dict[str, Any]) -> int | None:
    """从课程列表条目中解析 termId。

    注意：SPOC 条目顶层的 ``id`` 是 courseId，termId 在 ``termPanel.id``；
    必须先看嵌套的学期容器，不能先取顶层 id。
    """
    for key in ("termPanel", "termDto", "term", "courseTerm"):
        nested = source.get(key)
        if isinstance(nested, dict):
            for field in ("id", "termId", "term_id"):
                value = _int_or_none(nested.get(field))
                if value:
                    return value

    candidates = _source_candidates(source)
    for candidate in candidates:
        for key in ("termId", "term_id"):
            value = _int_or_none(candidate.get(key))
            if value:
                return value

    # 最后才把 id 当作 termId（MOOC 条目通常以 termId 为主键）。
    for candidate in candidates:
        value = _int_or_none(candidate.get("id"))
        if value:
            return value
    return None


def build_course_without_tasks(source: dict[str, Any]) -> Course:
    """课程列表接口可能不返回完整结构时的兜底。"""
    sources = _source_candidates(source)
    course_dto = source.get("courseDto") if isinstance(source.get("courseDto"), dict) else {}
    term_dto = source.get("termDto") if isinstance(source.get("termDto"), dict) else {}
    term_panel = source.get("termPanel") if isinstance(source.get("termPanel"), dict) else {}
    school_panel = source.get("schoolPanel") if isinstance(source.get("schoolPanel"), dict) else {}
    term_id = (
        _int_or_none(term_panel.get("id"))
        or _int_or_none(term_dto.get("id"))
        or _int_or_none(term_dto.get("termId"))
        or extract_term_id(source)
        or 0
    )
    course_id = (
        _int_or_none(source.get("id"))
        or _int_or_none(term_panel.get("courseId"))
        or _int_or_none(course_dto.get("id"))
        or _int_or_none(_from_sources(sources, "courseId", "course_id"))
    )
    name = str(
        source.get("name")
        or course_dto.get("name")
        or _from_sources(sources, "courseName", "name", "title")
        or ""
    )
    school = str(
        school_panel.get("name")
        or source.get("schoolName")
        or course_dto.get("schoolName")
        or _from_sources(sources, "schoolName", "school")
        or ""
    )
    if not school:
        for candidate in sources:
            panel = candidate.get("schoolPanel")
            if isinstance(panel, dict) and panel.get("name"):
                school = str(panel["name"])
                break
    return Course(
        term_id=term_id,
        course_id=course_id,
        name=name,
        school=school,
        school_short_name=str(
            school_panel.get("shortName")
            or source.get("schoolShortName")
            or course_dto.get("schoolShortName")
            or _from_sources(sources, "schoolShortName")
            or ""
        ),
        is_spoc=_is_spoc_source(source),
        start=_ms_to_dt(_from_sources(sources, "startTime", "start")),
        end=_ms_to_dt(_from_sources(sources, "endTime", "end")),
    )


def summarise(courses: list[Course]) -> dict[str, Any]:
    counts = {DONE: 0, PENDING: 0, UPCOMING: 0, OVERDUE: 0}
    for course in courses:
        for task in course.tasks:
            counts[task.status] = counts.get(task.status, 0) + 1
    counts["total"] = sum(counts.values())
    counts["courses"] = len(courses)
    return counts
