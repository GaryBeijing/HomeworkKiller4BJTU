# -*- coding: utf-8 -*-
# 作者: Gary
# 编写日期: 2026-10-31 20:45
# 文件名: bank.py
# 主要用途: 题库加载、题干归一化匹配与答案到选项编码的解析。
# 文件版本: 1.0.0
"""题库与答案解析。

完整保留原版 ``hsr_bank.py`` 的匹配语义：
1. 题干归一化后优先精确匹配；
2. 精确未命中时使用保守模糊匹配（相似度阈值 0.90）；
3. 有题库答案选项时按“选项原文”匹配考卷选项，字母仅作兜底；
4. 兼容单选、多选与判断题。
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections.abc import Sequence
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Final

__version__ = "1.0.0"
__all__ = [
    "Bank",
    "BankItem",
    "Option",
    "load_items_from_file",
    "load_rows",
    "normalize",
    "option_letter_map",
    "strip_option_prefix",
    "strip_question_number",
]

# 题库条目：q=题干，a=答案，t=题型，nq=归一化题干，其余字段原样保留。
BankItem = dict[str, Any]
# 考卷选项：optionCode 为唯一编码，optionsContent 为选项原文。
Option = dict[str, Any]

QUESTION_KEYS: Final[tuple[str, ...]] = (
    "题目", "题干", "问题", "试题", "question", "content", "title",
)
ANSWER_KEYS: Final[tuple[str, ...]] = (
    "答案", "正确答案", "标准答案", "answer", "key", "correct",
)
TYPE_KEYS: Final[tuple[str, ...]] = ("题型", "类型", "type")

_PUNCT: Final[frozenset[str]] = frozenset(
    "，。、；：？！“”‘’（）()【】[]《》<>·—…,.;:?!\"'`~-_=+*/\\|@#$%^&{}[]"
)
_OPT_PREFIX: Final[re.Pattern[str]] = re.compile(r"^\s*([A-Za-z])\s*[）).、:：]")

_TRUE_WORDS: Final[frozenset[str]] = frozenset(
    {"对", "正确", "是", "true", "t", "y", "√", "yes", "1"}
)
_FALSE_WORDS: Final[frozenset[str]] = frozenset(
    {"错", "错误", "否", "false", "f", "n", "×", "x", "no", "0"}
)


def normalize(value: object) -> str:
    """归一化文本，用于题干与选项比较。

    处理步骤：NFKC → 去首尾空白 → 转小写 → 去所有空白 → 去标点。

    Args:
        value: 任意文本值，``None`` 视为空串。

    Returns:
        归一化后的字符串。
    """
    if value is None:
        return ""
    text: str = unicodedata.normalize("NFKC", str(value)).strip().lower()
    text = re.sub(r"\s+", "", text)
    return "".join(char for char in text if char not in _PUNCT)


def strip_question_number(value: str) -> str:
    """去掉题干开头的题号，如 ``1.``、``2、``、``第3题``。

    Args:
        value: 原始题干。

    Returns:
        去掉开头题号后的题干。
    """
    return re.sub(r"^(第)?\d+(题|[.、)．])\s*", "", value)


def strip_option_prefix(value: object) -> str:
    """去掉选项原文前的字母前缀，如 ``"D）20%"`` -> ``"20%"``。

    Args:
        value: 选项原文。

    Returns:
        去掉字母前缀后的文本。
    """
    return _OPT_PREFIX.sub("", str(value or ""))


def option_letter_map(options: Sequence[Option]) -> tuple[dict[str, str], str]:
    """构建“选项字母 -> optionCode”的映射。

    Args:
        options: 考卷选项列表。

    Returns:
        ``(字母映射, 来源)``；来源为 ``"prefix"`` 或 ``"index"``。
    """
    by_letter: dict[str, str] = {}
    for option in options:
        match: re.Match[str] | None = _OPT_PREFIX.match(
            str(option.get("optionsContent") or "")
        )
        if match:
            by_letter[match.group(1).upper()] = str(option.get("optionCode"))
    if len(by_letter) >= 2:
        return by_letter, "prefix"
    return {
        chr(65 + index): str(option.get("optionCode"))
        for index, option in enumerate(options)
    }, "index"


def _pick(header: Sequence[str], keys: Sequence[str]) -> str | None:
    """在表头中寻找匹配的列名。

    Args:
        header: 表头行。
        keys: 候选列名关键字。

    Returns:
        命中的表头文本；未命中返回 ``None``。
    """
    for column in header:
        normalized_column: str = normalize(column)
        for key in keys:
            normalized_key: str = normalize(key)
            if normalized_key == normalized_column or normalized_key in normalized_column:
                return column
    return None


def _rows_from_csv(path: Path) -> list[list[str]]:
    """读取 CSV/TSV/TXT 题库为二维字符串表。

    Args:
        path: 文件路径。

    Returns:
        行列表。

    Raises:
        RuntimeError: 所有候选编码都无法解码时抛出。
    """
    for encoding in ("utf-8-sig", "gbk", "utf-8"):
        try:
            with path.open(newline="", encoding=encoding) as fp:
                sample: str = fp.read(4096)
                fp.seek(0)
                delimiter: str = "\t" if sample.count("\t") > sample.count(",") else ","
                return [list(row) for row in csv.reader(fp, delimiter=delimiter)]
        except UnicodeDecodeError:
            continue
    raise RuntimeError("无法识别文件编码: %s" % path)


def _rows_from_xlsx(path: Path) -> list[list[str]]:
    """读取 Excel 题库为二维字符串表。

    Args:
        path: ``.xlsx`` / ``.xlsm`` 文件路径。

    Returns:
        行列表。

    Raises:
        RuntimeError: 未安装 openpyxl 或文件无法读取时抛出。
    """
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("读取 Excel 题库需要安装 openpyxl") from exc
    workbook: Any = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows: list[list[str]] = []
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows(values_only=True):
            rows.append(["" if cell is None else str(cell) for cell in row])
    return rows


def _rows_from_docx(path: Path) -> list[list[str]]:
    """读取 Word 题库为二维字符串表。

    Args:
        path: ``.docx`` 文件路径。

    Returns:
        行列表。

    Raises:
        RuntimeError: 未安装 python-docx 或文件无法读取时抛出。
    """
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("读取 Word 题库需要安装 python-docx") from exc
    document: Any = Document(path)
    return [[paragraph.text] for paragraph in document.paragraphs if paragraph.text.strip()]


def _json_to_rows(data: Any) -> tuple[list[dict[str, Any]], list[list[str]]]:
    """把 JSON 题库拆分为“完整条目”和“二维表行”。

    Args:
        data: ``json.load`` 的结果。

    Returns:
        ``(条目列表, 行列表)``；条目列表保留 ``answer_options`` 等扩展字段。
    """
    if isinstance(data, dict):
        data = data.get("items") or data.get("questions") or list(data.values())
    items: list[dict[str, Any]] = []
    rows: list[list[str]] = []
    if not isinstance(data, list):
        return items, rows
    for entry in data:
        if isinstance(entry, dict):
            question: Any = (
                entry.get("question") or entry.get("content")
                or entry.get("题目") or entry.get("题干")
            )
            answer: Any = entry.get("answer") or entry.get("答案") or entry.get("correct")
            if not question or not answer:
                continue
            items.append({
                "question": str(question),
                "answer": str(answer),
                "type": str(entry.get("type") or entry.get("题型") or ""),
                "chapter": str(entry.get("chapter") or ""),
                "section": str(entry.get("section") or ""),
                "answer_options": entry.get("answer_options"),
            })
        elif isinstance(entry, (list, tuple)):
            rows.append([str(cell) for cell in entry])
    return items, rows


def _rows_to_items(rows: list[list[str]]) -> list[dict[str, Any]]:
    """把二维表转换为题库条目，自动识别表头。

    Args:
        rows: 二维字符串表。

    Returns:
        题库条目列表。
    """
    filtered: list[list[str]] = [
        row for row in rows if any(str(cell).strip() for cell in row)
    ]
    if not filtered:
        return []

    header: list[str] = filtered[0]
    question_column: str | None = _pick(header, QUESTION_KEYS)
    answer_column: str | None = _pick(header, ANSWER_KEYS)
    type_column: str | None = _pick(header, TYPE_KEYS)

    if question_column is None or answer_column is None:
        # 无表头：默认第 1 列为题目、第 2 列为答案。
        body: list[list[str]] = filtered
        question_index: int = 0
        answer_index: int = 1
        type_index: int | None = None
    else:
        body = filtered[1:]
        question_index = header.index(question_column)
        answer_index = header.index(answer_column)
        type_index = header.index(type_column) if type_column else None

    items: list[dict[str, Any]] = []
    for row in body:
        if len(row) <= max(question_index, answer_index):
            continue
        question: str = str(row[question_index]).strip()
        answer: str = str(row[answer_index]).strip()
        if not question or not answer:
            continue
        question_type: str = (
            str(row[type_index]).strip()
            if type_index is not None and type_index < len(row) else ""
        )
        items.append({"question": question, "answer": answer, "type": question_type})
    return items


def load_rows(path: Path) -> list[list[str]]:
    """按扩展名读取题库文件为二维字符串表。

    Args:
        path: 题库文件路径。

    Returns:
        行列表。

    Raises:
        RuntimeError: 扩展名不受支持时抛出。
    """
    extension: str = path.suffix.lower()
    if extension in (".xlsx", ".xlsm"):
        return _rows_from_xlsx(path)
    if extension == ".docx":
        return _rows_from_docx(path)
    if extension == ".json":
        with path.open(encoding="utf-8") as fp:
            data: Any = json.load(fp)
        items, rows = _json_to_rows(data)
        # JSON 条目数据转成带表头的二维表，便于复用表头识别逻辑。
        if items:
            return [
                ["question", "answer", "type"],
                *[[item["question"], item["answer"], item["type"]] for item in items],
            ]
        return rows
    if extension in (".csv", ".tsv", ".txt"):
        return _rows_from_csv(path)
    raise RuntimeError("不支持的题库格式: %s" % extension)


def load_items_from_file(path: Path) -> list[dict[str, Any]]:
    """读取任意受支持格式的题库文件，返回原始条目。

    JSON 文件会保留 ``answer_options`` 等扩展字段；其他格式走表头识别。

    Args:
        path: 题库文件路径。

    Returns:
        题库条目列表。

    Raises:
        RuntimeError: 文件格式不支持或内容无法解析时抛出。
    """
    if path.suffix.lower() == ".json":
        with path.open(encoding="utf-8") as fp:
            data: Any = json.load(fp)
        items, rows = _json_to_rows(data)
        if items:
            return items
        return _rows_to_items(rows)
    return _rows_to_items(load_rows(path))


class Bank:
    """内存题库与匹配器。"""

    def __init__(self, items: Sequence[dict[str, Any]]) -> None:
        """构建题库索引。

        Args:
            items: 原始题库条目列表。
        """
        self._items: list[BankItem] = []
        self._index: dict[str, list[BankItem]] = {}
        for raw_item in items:
            if not isinstance(raw_item, dict):
                continue
            question: Any = raw_item.get("question") or raw_item.get("q")
            answer: Any = raw_item.get("answer") or raw_item.get("a")
            if not question or not answer:
                continue
            normalized_question: str = strip_question_number(normalize(question))
            item: BankItem = {
                "q": str(question),
                "a": str(answer),
                "t": str(raw_item.get("type") or raw_item.get("t") or ""),
                "chapter": str(raw_item.get("chapter") or ""),
                "section": str(raw_item.get("section") or ""),
                "answer_options": self._normalize_answer_options(
                    raw_item.get("answer_options")
                ),
                "nq": normalized_question,
            }
            self._items.append(item)
            self._index.setdefault(normalized_question, []).append(item)

    @staticmethod
    def _normalize_answer_options(value: Any) -> list[dict[str, str]] | None:
        """规范题库答案选项结构。

        Args:
            value: 原始 ``answer_options`` 值。

        Returns:
            统一为 ``[{"letter": str, "text": str}, ...]``；无有效项返回 ``None``。
        """
        if not isinstance(value, list):
            return None
        options: list[dict[str, str]] = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            letter: str = str(entry.get("letter") or "").upper()
            text: str = str(entry.get("text") or entry.get("content") or "")
            if letter or text:
                options.append({"letter": letter, "text": text})
        return options or None

    @classmethod
    def from_file(cls, path: Path) -> "Bank":
        """从题库文件构建 :class:`Bank`。

        Args:
            path: 题库文件路径。

        Returns:
            构建完成的题库对象。
        """
        return cls(load_items_from_file(path))

    @property
    def items(self) -> list[BankItem]:
        """返回题库条目列表副本。

        Returns:
            条目列表。
        """
        return list(self._items)

    @property
    def count(self) -> int:
        """返回题目数量。

        Returns:
            题目数量。
        """
        return len(self._items)

    def lookup_item(
        self,
        question: str,
        threshold: float = 0.90,
    ) -> tuple[BankItem | None, float, str | None]:
        """按题干查找题库条目。

        Args:
            question: 待匹配题干。
            threshold: 模糊匹配最低相似度。

        Returns:
            ``(条目, 相似度, 匹配方式)``；未命中时条目为 ``None``。
        """
        normalized_question: str = strip_question_number(normalize(question))
        if not normalized_question:
            return None, 0.0, None

        # 步骤 1：精确匹配（哈希索引，O(1)）。
        if normalized_question in self._index:
            hits: list[BankItem] = self._index[normalized_question]
            answers: set[str] = {hit["a"] for hit in hits}
            method: str = "exact" if len(answers) == 1 else "exact-conflict"
            return hits[0], 1.0, method

        # 步骤 2：保守模糊匹配，仅当相似度达到阈值时才采用。
        best_score: float = 0.0
        best_item: BankItem | None = None
        for item in self._items:
            score: float = SequenceMatcher(None, normalized_question, item["nq"]).ratio()
            if score > best_score:
                best_score = score
                best_item = item
        if best_score >= threshold and best_item is not None:
            return best_item, best_score, "fuzzy"
        return None, best_score, None

    def lookup(
        self,
        question: str,
        threshold: float = 0.90,
    ) -> tuple[str | None, float, str | None]:
        """按题干查找答案文本。

        Args:
            question: 待匹配题干。
            threshold: 模糊匹配最低相似度。

        Returns:
            ``(答案文本, 相似度, 匹配方式)``；未命中时答案文本为 ``None``。
        """
        item, score, method = self.lookup_item(question, threshold)
        if item is None:
            return None, score, method
        return item["a"], score, method

    def resolve_answer_options(
        self,
        answer_options: Sequence[dict[str, str]] | None,
        options: Sequence[Option],
        multi: bool = False,
        trace: list[bool] | None = None,
    ) -> list[str]:
        """把题库答案选项按原文匹配到考卷选项。

        Args:
            answer_options: 题库答案选项（``letter`` + ``text``）。
            options: 考卷选项列表。
            multi: 是否为多选题。
            trace: 若传入列表，会为每个答案选项追加是否靠原文匹配成功的标记。

        Returns:
            匹配到的 ``optionCode`` 列表；单选最多返回一个。
        """
        if not answer_options or not options:
            return []

        letter_map, _source = option_letter_map(options)
        normalized_options: list[tuple[Option, str]] = [
            (option, normalize(strip_option_prefix(option.get("optionsContent"))))
            for option in options
        ]
        picked: list[str] = []

        for answer_option in answer_options:
            answer_text: str = normalize(strip_option_prefix(answer_option.get("text", "")))
            answer_letter: str = str(answer_option.get("letter") or "").upper()
            code: str | None = None
            text_hit: bool = False

            if answer_text:
                # 步骤 1：选项原文完全相同。
                exact_matches: list[Option] = [
                    option for option, normalized in normalized_options
                    if normalized == answer_text
                ]
                if exact_matches:
                    code = str(exact_matches[0]["optionCode"])
                    text_hit = True
                else:
                    # 步骤 2：题库答案只写了选项的一部分（至少 4 字才允许包含匹配）。
                    contained: list[Option] = [
                        option for option, normalized in normalized_options
                        if len(answer_text) >= 4 and normalized and answer_text in normalized
                    ]
                    if len(contained) == 1:
                        code = str(contained[0]["optionCode"])
                        text_hit = True
                if code is None:
                    # 步骤 3：高相似度模糊匹配，阈值 0.90。
                    best_score: float = 0.0
                    best_option: Option | None = None
                    for option, normalized in normalized_options:
                        score: float = SequenceMatcher(None, answer_text, normalized).ratio()
                        if score > best_score:
                            best_score = score
                            best_option = option
                    if best_score >= 0.90 and best_option is not None:
                        code = str(best_option["optionCode"])
                        text_hit = True

            # 步骤 4：文本匹配失败时，才用题库字母兜底。
            if code is None and answer_letter:
                code = letter_map.get(answer_letter)
            if code is None and answer_letter and "A" <= answer_letter <= "H":
                index: int = ord(answer_letter) - 65
                if index < len(options):
                    code = str(options[index]["optionCode"])

            if code and code not in picked:
                picked.append(code)
            if trace is not None:
                trace.append(text_hit)

        return picked if multi else picked[:1]

    def resolve_answer(
        self,
        answer_text: str | None,
        options: Sequence[Option],
        multi: bool = False,
    ) -> list[str]:
        """把答案文本解析为考卷选项编码。

        支持选项字母、选项原文、判断题关键词三种写法。

        Args:
            answer_text: 题库答案文本。
            options: 考卷选项列表。
            multi: 是否为多选题。

        Returns:
            匹配到的 ``optionCode`` 列表；单选最多返回一个。
        """
        if answer_text is None or not options:
            return []

        normalized_answer: str = unicodedata.normalize("NFKC", str(answer_text)).strip()
        letter_map, _source = option_letter_map(options)
        contents: list[str] = [str(option.get("optionsContent") or "") for option in options]

        # 步骤 1：整串仅由字母与分隔符组成时，按选项字母解释。
        compact: str = re.sub(r"[\s,，、;；/|]+", "", normalized_answer).upper()
        if compact and re.fullmatch(r"[A-H]{1,8}", compact) and all(
            char in letter_map for char in compact
        ):
            picked: list[str] = []
            for char in compact:
                code: str = letter_map[char]
                if code not in picked:
                    picked.append(code)
            return picked if multi else picked[:1]

        # 步骤 2：判断题关键词。
        key: str = re.sub(r"[\s，。、；:：.()（）]", "", normalized_answer).lower()
        if key in _TRUE_WORDS or key in _FALSE_WORDS:
            want: str = "对" if key in _TRUE_WORDS else "错"
            for option, content in zip(options, contents):
                normalized_content: str = normalize(strip_option_prefix(content))
                expected: str = normalize(want)
                alternative: str = normalize("正确" if want == "对" else "错误")
                if normalized_content in {expected, alternative}:
                    return [str(option.get("optionCode"))]
            if len(options) == 2:
                return [str(options[0 if want == "对" else 1].get("optionCode"))]

        # 步骤 3：选项原文精确/包含匹配。
        normalized_target: str = normalize(strip_option_prefix(normalized_answer))
        content_picked: list[str] = []
        for option, content in zip(options, contents):
            normalized_content = normalize(strip_option_prefix(content))
            if normalized_content and (
                normalized_content == normalized_target
                or normalized_content in normalized_target
            ):
                content_picked.append(str(option.get("optionCode")))
        if content_picked:
            content_picked = [code for code in content_picked if code]
            return content_picked if multi else content_picked[:1]

        # 步骤 4：模糊匹配，阈值 0.85（保持原版行为）。
        best_score = 0.0
        best_code: str | None = None
        for option, content in zip(options, contents):
            score: float = SequenceMatcher(
                None, normalized_target, normalize(strip_option_prefix(content))
            ).ratio()
            if score > best_score:
                best_score = score
                best_code = str(option.get("optionCode"))
        if best_score >= 0.85 and best_code:
            return [best_code]
        return []
