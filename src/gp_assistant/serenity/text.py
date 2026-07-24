from __future__ import annotations

import re


# CNINFO currently returns some Chinese metadata and PDF text with GBK bytes
# decoded as UTF-8.  The replacement characters make a general round-trip
# impossible, but the bounded decision vocabulary can be repaired
# deterministically without guessing arbitrary prose.
_DECISION_VOCABULARY = (
    "证券代码",
    "证券简称",
    "公告编号",
    "业绩预告修正公告",
    "业绩预告更正公告",
    "业绩预告",
    "业绩快报",
    "净利润",
    "归属于上市公司股东",
    "同比增长",
    "同比增加",
    "同比上升",
    "同比下降",
    "同比减少",
    "亏损收窄",
    "亏损减少",
    "减亏",
    "扭亏为盈",
    "增长",
    "增加",
    "上升",
    "盈利",
    "下降",
    "减少",
    "下滑",
    "亏损",
    "立案调查",
    "行政处罚",
    "纪律处分",
    "监管措施",
    "调查通知",
    "重大诉讼",
    "重大仲裁",
    "诉讼",
    "仲裁",
    "胜诉",
    "和解",
    "撤诉",
    "驳回",
    "终止",
    "撤回",
    "取消",
    "更正",
    "修订",
    "补充公告",
    "重大资产重组",
    "控制权变更",
    "非公开发行",
    "定向增发",
    "重大项目",
    "回购",
    "增持",
    "减持",
    "中标",
    "合同",
)


def _broken_gbk_variant(value: str) -> str:
    return value.encode("gb18030").decode("utf-8", errors="replace")


_REPAIRS = tuple(
    sorted(
        (
            (broken, value)
            for value in _DECISION_VOCABULARY
            if (broken := _broken_gbk_variant(value)) != value and "�" not in broken
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)


def normalize_cn_text(value: object) -> str:
    """Normalize bounded CNINFO mojibake while preserving the original evidence elsewhere."""

    text = str(value or "")
    for broken, repaired in _REPAIRS:
        text = text.replace(broken, repaired)
    return text


def best_document_title(metadata_title: object, extracted_text: object) -> str:
    """Prefer metadata unless it is visibly corrupted; otherwise use the PDF heading."""

    title = normalize_cn_text(metadata_title).strip()
    replacement_ratio = title.count("�") / max(1, len(title))
    if title and replacement_ratio < 0.08 and re.search(r"[\u4e00-\u9fff]", title):
        return title[:240]
    text = normalize_cn_text(extracted_text)
    fallback = ""
    for raw_line in text.splitlines()[:20]:
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or re.match(r"^(证券代码|证券简称|公告编号)\s*[:：]", line):
            continue
        if any(
            token in line
            for token in (
                "业绩预告",
                "业绩快报",
                "立案",
                "处罚",
                "诉讼",
                "仲裁",
                "终止",
                "撤回",
                "更正",
                "修订",
            )
        ):
            return line[:240]
        if not fallback and re.search(r"[\u4e00-\u9fff]", line):
            fallback = line[:240]
    return fallback or title[:240]
