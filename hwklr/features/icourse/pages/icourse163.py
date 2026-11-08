# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-11-08 14:30
# 文件名: icourse163.py
# 主要用途: icourse163 页面 URL、选择器、SPA 导航与视频状态脚本。
# 文件版本: 4.0.0
"""icourse163 页面 URL 与选择器。

结构基于 2026-11 的新版 React 学习页：
- 学习页 tabs: ``li.ant-menu-item``
- 章节: ``.m-learnChapterNormal``
- 小节: ``.u-learnLesson``
- 单元条目: ``.f-icon.lsicon[data-cid=<unitId>]``
- 视频页 URL hash: ``#/learn/content?type=detail&id=<lessonId>&cid=<unitId>``
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

BASE = "https://www.icourse163.org"
LEARN_PATH = "/learn/{school}-{course_id}?tid={term_id}"
SPOC_LEARN_PATH = "/spoc/learn/{school}-{course_id}?tid={term_id}"

CONTENT_SELECTORS = {
    "tab": "li.ant-menu-item",
    "chapter": ".m-learnChapterNormal, .m-learnChapterList",
    "lesson": ".u-learnLesson",
    "unit": ".f-icon.lsicon[data-cid]",
    "modal_button": "button",
    "video": "video",
    "player": "#j-video-player, .ux-video-player",
    "quiz_dialog": (
        "[class*=quizDialog], [class*=QuizDialog], [class*=questionDialog], "
        "[class*=QuestionDialog], .u-edu-h5player-popmenu"
    ),
}

DOCUMENT_SELECTORS = {
    "pdf": "a.j-downpdf",
    "attachment": "a.j-downtxt",
}

_KIND_PATTERNS = (
    ("视频", ("视频",)),
    ("文档", ("文档", "课件")),
    ("讨论", ("讨论",)),
    ("测验", ("测验", "测试")),
    ("作业", ("作业",)),
    ("考试", ("考试",)),
)


def learn_url(
    school: str,
    course_id: int | str,
    term_id: int | str,
    *,
    spoc: bool = False,
) -> str:
    template = SPOC_LEARN_PATH if spoc else LEARN_PATH
    return BASE + template.format(
        school=school, course_id=int(course_id), term_id=int(term_id)
    )


def content_base(
    school: str,
    course_id: int | str,
    term_id: int | str,
    *,
    spoc: bool = False,
) -> str:
    return learn_url(school, course_id, term_id, spoc=spoc) + "#/learn/content"


def open_route(
    page: Page,
    base_url: str,
    hash_path: str,
    *,
    wait_ms: int = 1800,
) -> Page:
    """进入 SPA 的某个 hash 路由。

    新版学习页对「冷启动时带 hash 的 goto」处理不稳定，先加载 base，
    再通过 ``location.hash`` 触发路由，实测最可靠。
    """
    target_base = base_url.split("#", 1)[0]
    # 每次都重新加载 base：新版 SPA 在不同路由间切换时可能残留旧状态
    # （典型现象：测验页提示「请登录后操作」）。
    page.goto(target_base, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(2500)
    value = hash_path if hash_path.startswith("#") else f"#{hash_path}"
    page.evaluate("(value) => { location.hash = value; }", value)
    page.wait_for_timeout(wait_ms)
    return page


def content_url(
    school: str,
    course_id: int | str,
    term_id: int | str,
    lesson_id: int | str,
    unit_id: int | str,
    *,
    spoc: bool = False,
) -> str:
    return (
        content_base(school, course_id, term_id, spoc=spoc)
        + f"?type=detail&id={int(lesson_id)}&cid={int(unit_id)}"
    )


def testlist_url(
    school: str, course_id: int | str, term_id: int | str, *, spoc: bool = False
) -> str:
    return learn_url(school, course_id, term_id, spoc=spoc) + "#/learn/testlist"


def forum_url(
    school: str, course_id: int | str, term_id: int | str, *, spoc: bool = False
) -> str:
    return learn_url(school, course_id, term_id, spoc=spoc) + "#/learn/forumindex"


def is_spoc_url(url: str) -> bool:
    return "/spoc/learn/" in str(url)


def page_block_reason(page: Page) -> str:
    """返回学习页不可用的原因：未登录 / 被重定向到课程介绍页。

    未登录时学习页经常不报错，而是跳到 ``/course/...`` 或只显示
    「登录 | 注册」；这里在等待 video/题目/讨论前先快速判定。
    """
    try:
        return str(
            page.evaluate(
                r"""() => {
                  const url = location.href || '';
                  if (/\/course\//.test(url) && !/\/learn\//.test(url)) {
                    return '页面被重定向到课程介绍页（登录态失效或未选课）';
                  }
                  const text = document.body ? document.body.innerText : '';
                  const hasContent = !!document.querySelector(
                    'video, .u-questionItem, .j-reply-all, .m-learnChapterNormal'
                  );
                  const isSpoc = /\/spoc\//.test(url);
                  if (!isSpoc && !hasContent &&
                      (/登录\s*\|\s*注册/.test(text) ||
                       text.includes('请登录后操作'))) {
                    return '页面要求登录（登录态已失效）';
                  }
                  return '';
                }"""
            )
            or ""
        )
    except Exception:
        return ""


@dataclass(frozen=True)
class CourseUrls:
    school: str
    course_id: int
    term_id: int
    is_spoc: bool = False

    @property
    def learn(self) -> str:
        return learn_url(
            self.school, self.course_id, self.term_id, spoc=self.is_spoc
        )


# --------------------------------------------------------------------- 页面操作
def close_modals(page: Page, *, timeout: int = 1500) -> int:
    """关闭「非法跨域请求 / 并发限制 / 知道了」等提示弹窗。"""
    closed = 0
    for _ in range(12):
        try:
            clicked = page.evaluate(
                r"""
                () => {
                  const labels = new Set(['知道了', '确定', '关闭', 'OK']);
                  const nodes = [...document.querySelectorAll(
                    'button,a,span,.ux-modal-btn,.ux-btn,.u-btn,[role=button],.ux-modal_close'
                  )];
                  for (const node of nodes) {
                    const text = (node.innerText || '').trim();
                    if (!labels.has(text)) continue;
                    const rect = node.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                      node.click();
                      return text;
                    }
                  }
                  const close = document.querySelector('.ux-modal_close, .u-icon-normal-close');
                  if (close && close.getBoundingClientRect().height > 0) {
                    close.click();
                    return 'x';
                  }
                  return '';
                }
                """
            )
        except Exception:
            # 页面正在导航/刷新时执行上下文会失效，交给调用方重试。
            break
        if not clicked:
            break
        closed += 1
        page.wait_for_timeout(300)
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    return closed


def click_tab(page: Page, name: str, *, timeout: int = 5000) -> None:
    tab = page.locator(CONTENT_SELECTORS["tab"]).filter(has_text=name).first
    tab.click(timeout=timeout)
    page.wait_for_timeout(1200)


def unit_kind(text: str) -> str:
    head = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    for label, needles in _KIND_PATTERNS:
        if any(needle in head for needle in needles):
            return label
    return "其他"


def unit_name(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    # 第一行是类型（视频/文档/...），第二行是名字。
    return lines[1] if len(lines) > 1 else lines[0]


def iter_unit_elements(page: Page):
    return page.locator(CONTENT_SELECTORS["unit"]).all()


VIDEO_WATCH_JS = r"""
() => {
  const v = document.querySelector('video');
  if (!v) return false;
  const state = window.__moocokVideo || (window.__moocokVideo = {
    ended: false, max: 0, last: 0, resets: 0
  });
  if (!v.__moocokBound) {
    v.__moocokBound = true;
    v.addEventListener('ended', () => { state.ended = true; });
    v.addEventListener('timeupdate', () => {
      const duration = v.duration || 0;
      const current = v.currentTime || 0;
      // 真实播放器结束后会把 currentTime 归零；高水位已接近末尾时
      // 观察到归零，等价于 ended，避免轮询错过 ended 事件。
      if (state.last > 1 && current + 1 < state.last) {
        state.resets += 1;
        if (duration > 0 && state.last >= duration - 3) state.ended = true;
      }
      state.last = current;
      if (current > state.max) state.max = current;
    });
  }
  if ((v.currentTime || 0) > state.max) state.max = v.currentTime;
  return true;
}
"""


def install_video_watch(page: Page) -> bool:
    """在 video 元素上挂 ended/timeupdate 监听，并重置高水位。

    结束后播放器常把 ``currentTime`` 重置为 0，单靠轮询会错过
    ``ended`` 并一直等下去；监听里记录高水位和“接近末尾后归零”。
    """
    try:
        page.evaluate(
            """() => {
              window.__moocokVideo = {ended:false, max:0, last:0, resets:0};
            }"""
        )
        return bool(page.evaluate(VIDEO_WATCH_JS))
    except Exception:
        return False


def set_video_rate(page: Page, rate: float = 2.0, *, muted: bool = True) -> dict:
    """设置视频倍速/静音并播放，返回当前状态。"""
    try:
        return page.evaluate(
            """({rate, muted}) => {
              const v = document.querySelector('video');
              if (!v) return {ok:false, reason:'no-video'};
              v.playbackRate = rate;
              v.muted = muted;
              v.play().catch(() => {});
              return {ok:true, rate:v.playbackRate, muted:v.muted, paused:v.paused,
                      duration:v.duration, currentTime:v.currentTime,
                      ended:v.ended, readyState:v.readyState};
            }""",
            {"rate": rate, "muted": muted},
        )
    except Exception:
        return {"ok": False, "reason": "navigation"}


def video_state(page: Page) -> dict:
    try:
        return page.evaluate(
            """() => {
              const v = document.querySelector('video');
              if (!v) return {ok:false};
              const watched = window.__moocokVideo;
              return {ok:true, rate:v.playbackRate, muted:v.muted, paused:v.paused,
                      duration:v.duration, currentTime:v.currentTime,
                      ended:v.ended || !!(watched && watched.ended),
                      max:Math.max(v.currentTime || 0,
                                   (watched && watched.max) || 0),
                      resets:(watched && watched.resets) || 0,
                      readyState:v.readyState, src:v.currentSrc || v.src};
            }"""
        )
    except Exception:
        return {"ok": False, "reason": "navigation"}


def wait_video_end(
    page: Page, *, poll_ms: int = 2000, timeout_ms: int = 3 * 60 * 60 * 1000
) -> bool:
    """等待视频结束；超时返回 False。"""
    install_video_watch(page)
    elapsed = 0
    max_current = 0.0
    while elapsed < timeout_ms:
        state = video_state(page)
        if not state.get("ok"):
            page.wait_for_timeout(poll_ms)
            elapsed += poll_ms
            continue
        max_current = max(
            max_current,
            float(state.get("currentTime") or 0),
            float(state.get("max") or 0),
        )
        if state.get("ended"):
            return True
        duration = float(state.get("duration") or 0)
        if duration > 0 and max_current >= duration - 2:
            return True
        page.wait_for_timeout(poll_ms)
        elapsed += poll_ms
    return False


def parse_cid_from_hash(url: str) -> int | None:
    match = re.search(r"[?&]cid=(\d+)", url or "")
    return int(match.group(1)) if match else None


def page_alerts(page: Page) -> list[str]:
    """读取页面上可见的限流/登录提示，供并发探针判定。"""
    try:
        return page.evaluate(
            """() => {
              const hits = ['并发限制', '请稍后再试', '操作过于频繁',
                            '请登录', '登录已失效', '尚未登录'];
              const nodes = [...document.querySelectorAll(
                '.ux-modal, .ant-modal, .ant-message, .ux-toast, .u-tip, [class*=toast]'
              )].filter(el => {
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
              });
              const text = nodes.map(el => el.innerText || '').join(' ');
              return hits.filter(hit => text.includes(hit));
            }"""
        ) or []
    except Exception:
        return []
