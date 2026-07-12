from __future__ import annotations

import io
import multiprocessing
import re
from hashlib import sha256
from typing import Any, Dict, List, Tuple

from .models import SerenityFact, SerenityHypothesis
from .text import normalize_cn_text


_PERFORMANCE = re.compile(r"业绩(?:预告|快报)|净利润", re.I)
_POSITIVE = re.compile(r"(?:增长|增加|上升|扭亏|盈利)[^。；]{0,50}?(\d+(?:\.\d+)?)\s*%(?:[^。；]{0,20}?(\d+(?:\.\d+)?)\s*%)?", re.I)
_NEGATIVE = re.compile(r"(?:下降|减少|下滑|亏损)[^。；]{0,50}?(\d+(?:\.\d+)?)\s*%(?:[^。；]{0,20}?(\d+(?:\.\d+)?)\s*%)?", re.I)
_IMPROVING_LOSS = re.compile(
    r"(?:减亏|亏损(?:额|幅度)?(?:同比)?(?:减少|下降|收窄)|亏损收窄)[^。；]{0,50}?(\d+(?:\.\d+)?)\s*%"
    r"(?:[^。；]{0,20}?(\d+(?:\.\d+)?)\s*%)?",
    re.I,
)
_ENFORCEMENT = re.compile(r"立案|行政处罚|纪律处分|监管措施|调查通知", re.I)
_LITIGATION = re.compile(r"重大(?:诉讼|仲裁)|重大诉讼|重大仲裁", re.I)
_TERMINATION = re.compile(r"终止|撤回|取消", re.I)
_REFERENCE_ONLY = re.compile(r"回购|增持|减持|中标|合同|更正", re.I)
_CORRECTION = re.compile(r"更正|修订|补充公告", re.I)
_RETRACTION = re.compile(r"(?:撤回|作废)[^。；]{0,20}?(?:公告|文件)|(?:公告|文件)[^。；]{0,20}?(?:撤回|作废)", re.I)
_NEGATED_ENFORCEMENT = re.compile(r"(?:未|不|不存在|未涉及|无需)[^。；]{0,12}?(?:立案|调查|处罚|处分|监管措施)", re.I)
_FAVORABLE_LITIGATION = re.compile(r"(?:胜诉|和解|撤诉|驳回|不存在|未涉及)[^。；]{0,20}?(?:诉讼|仲裁)|(?:诉讼|仲裁)[^。；]{0,20}?(?:胜诉|和解|撤诉|驳回|不存在)", re.I)
_FAVORABLE_RESOLUTION = re.compile(r"胜诉|和解|撤诉|驳回", re.I)
_TERMINATION_SUBJECT = re.compile(r"重大资产重组|控制权变更|收购|定向增发|非公开发行|重大项目", re.I)
_REPORT_PERIOD = re.compile(
    r"(20\d{2})\s*年?\s*(第一季度|一季度|半年度|上半年|前三季度|第三季度|三季度|年度|全年)",
    re.I,
)


def _relation_fact_types(title: str) -> List[str]:
    """Return only event families that an unresolved relation can safely freeze."""
    scopes: List[str] = []
    if _PERFORMANCE.search(title):
        scopes.append("earnings_guidance")
    if _ENFORCEMENT.search(title):
        scopes.append("regulatory_enforcement")
    if _LITIGATION.search(title):
        scopes.append("major_litigation")
    if _TERMINATION_SUBJECT.search(title):
        scopes.append("termination_or_withdrawal")
    return scopes


def _earnings_relation_key(value: str) -> str:
    match = _REPORT_PERIOD.search(value)
    if not match:
        return ""
    period = {
        "第一季度": "Q1",
        "一季度": "Q1",
        "半年度": "H1",
        "上半年": "H1",
        "前三季度": "Q3YTD",
        "第三季度": "Q3",
        "三季度": "Q3",
        "年度": "FY",
        "全年": "FY",
    }.get(match.group(2), "")
    return f"earnings_guidance:{match.group(1)}:{period}" if period else ""


def _extract_pdf_text_sync(
    data: bytes,
    *,
    max_pages: int,
    max_chars: int,
) -> Tuple[str, str]:
    try:
        from pypdf import PdfReader
    except Exception:
        return "", "parser_unavailable"
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        parts: List[str] = []
        total = 0
        page_count = len(reader.pages)
        truncated = page_count > max_pages
        for index in range(min(page_count, max_pages)):
            page = reader.pages[index]
            text = str(page.extract_text() or "")
            if not text:
                continue
            remaining = max_chars - total
            if remaining <= 0:
                truncated = True
                break
            parts.append(text[:remaining])
            total += min(len(text), remaining)
        joined = "\n".join(parts).strip()
        if not joined:
            return "", "unparsed"
        return joined, "truncated" if truncated or total >= max_chars else "parsed"
    except Exception:
        return "", "unparsed"


def _pdf_parse_process(
    sender: Any,
    data: bytes,
    max_pages: int,
    max_chars: int,
) -> None:
    try:
        sender.send(
            _extract_pdf_text_sync(
                data,
                max_pages=max_pages,
                max_chars=max_chars,
            )
        )
    except BaseException:
        try:
            sender.send(("", "unparsed"))
        except Exception:
            pass
    finally:
        sender.close()


def extract_pdf_text(
    data: bytes,
    *,
    max_pages: int = 80,
    max_chars: int = 250_000,
    timeout_sec: float = 20.0,
) -> Tuple[str, str]:
    """Parse an untrusted PDF in a disposable process with a hard wall-clock bound."""
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_pdf_parse_process,
        args=(sender, data, max(1, int(max_pages)), max(1, int(max_chars))),
        daemon=True,
    )
    try:
        process.start()
        sender.close()
        if not receiver.poll(max(0.1, float(timeout_sec))):
            return "", "parse_timeout"
        try:
            result = receiver.recv()
        except (EOFError, OSError):
            return "", "unparsed"
        if (
            not isinstance(result, tuple)
            or len(result) != 2
            or not all(isinstance(item, str) for item in result)
        ):
            return "", "unparsed"
        return result
    except Exception:
        return "", "parser_worker_unavailable"
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
        if process.pid is not None:
            process.join(timeout=2.0)


def _excerpt(text: str, pattern: re.Pattern[str], *, width: int = 220) -> str:
    match = pattern.search(text)
    if not match:
        return ""
    start = max(0, match.start() - width // 3)
    end = min(len(text), match.end() + 2 * width // 3)
    return re.sub(r"\s+", " ", text[start:end]).strip()[:width]


def _numbers(match: re.Match[str] | None) -> Dict[str, Any]:
    if match is None:
        return {}
    values: List[float] = []
    for value in match.groups():
        if value is None:
            continue
        try:
            values.append(float(value))
        except Exception:
            continue
    return {"percent_values": values}


def build_verified_evidence(
    *,
    symbol: str,
    title: str,
    text: str,
    published_at: str | None,
    effective_available_at: str,
    source_document_id: str,
    source_version_id: str,
    source_url: str,
    content_hash: str,
    source_verified: bool,
    backfill_only: bool,
) -> tuple[List[SerenityFact], List[SerenityHypothesis]]:
    title = normalize_cn_text(title)
    text = normalize_cn_text(text)
    combined = f"{title}\n{text}".strip()
    if not text.strip():
        return [], []
    compact_head = re.sub(r"\s+", "", text[:10_000])
    if symbol and symbol not in compact_head:
        return [], []
    event_type = ""
    direction = 0
    confidence = 0.0
    mechanism = ""
    expected = ""
    falsifiers: List[str] = []
    evidence = ""
    numeric: Dict[str, Any] = {}

    header = f"{title}\n{text[:1500]}"
    if _CORRECTION.search(title) or _RETRACTION.search(title):
        event_type, direction, confidence = "reference_only", 0, 0.60
        relation_pattern = _RETRACTION if _RETRACTION.search(title) else _CORRECTION
        relation_type = "retraction" if relation_pattern is _RETRACTION else "correction"
        evidence = _excerpt(combined, relation_pattern)
        numeric = {
            "relation_type": relation_type,
            "relation_status": "unresolved",
            "relation_fact_types": _relation_fact_types(title),
            "relation_target_keys": [key]
            if (key := _earnings_relation_key(title))
            else [],
        }
        mechanism = "更正或修订必须与原公告建立版本关系后才能判断方向。"
        expected = "仅作解释参考，不进入排序。"
        falsifiers = ["尚未完成原公告关系核验"]
    elif _PERFORMANCE.search(header):
        improving_loss = _IMPROVING_LOSS.search(combined)
        positive = _POSITIVE.search(combined)
        negative = _NEGATIVE.search(combined)
        if improving_loss and not positive:
            event_type, direction, confidence = "earnings_guidance", 1, 0.82
            evidence, numeric = _excerpt(combined, _IMPROVING_LOSS), _numbers(improving_loss)
            numeric["still_loss_making"] = True
            mechanism = "亏损同比收窄是盈利趋势改善，但公司仍可能处于亏损状态。"
            expected = "仅在价格与成交结构确认时，未来 1/3/5 个交易日相对表现可能改善。"
            falsifiers = ["绝对亏损继续扩大", "后续更正下调改善幅度", "市场已充分定价"]
        elif positive and not negative:
            event_type, direction, confidence = "earnings_guidance", 1, 0.92
            evidence, numeric = _excerpt(combined, _POSITIVE), _numbers(positive)
            mechanism = "已披露的盈利增长区间可能强化短期盈利预期。"
            expected = "未来 1/3/5 个交易日相对基准收益偏强。"
            falsifiers = ["后续更正下调盈利区间", "价格与成交结构未确认"]
        elif negative and not positive:
            event_type, direction, confidence = "earnings_guidance", -1, 0.92
            evidence, numeric = _excerpt(combined, _NEGATIVE), _numbers(negative)
            mechanism = "已披露的盈利下降或亏损区间可能削弱短期盈利预期。"
            expected = "未来 1/3/5 个交易日相对基准收益偏弱。"
            falsifiers = ["后续更正显著上调盈利区间", "市场已充分定价且结构转强"]
    if not event_type and _ENFORCEMENT.search(header) and _ENFORCEMENT.search(combined) and not _NEGATED_ENFORCEMENT.search(combined):
        event_type, direction, confidence = "regulatory_enforcement", -1, 0.90
        evidence = _excerpt(combined, _ENFORCEMENT)
        mechanism = "正式调查、处罚或纪律处分可能提高不确定性和风险溢价。"
        expected = "短期相对收益和成交承接弱于基准。"
        falsifiers = ["后续文件明确影响轻微或解除措施", "风险已被充分定价"]
    if (
        not event_type
        and _LITIGATION.search(header)
        and _LITIGATION.search(combined)
        and not _FAVORABLE_LITIGATION.search(combined)
        and not _FAVORABLE_RESOLUTION.search(combined)
    ):
        event_type, direction, confidence = "major_litigation", -1, 0.82
        evidence = _excerpt(combined, _LITIGATION)
        mechanism = "明确重大诉讼或仲裁可能增加现金流和估值不确定性。"
        expected = "未来 1/3/5 个交易日风险调整后表现偏弱。"
        falsifiers = ["后续胜诉或和解且影响可控", "涉案金额被证实不重大"]
    if not event_type and _TERMINATION.search(header) and _TERMINATION.search(combined) and _TERMINATION_SUBJECT.search(combined):
        event_type, direction, confidence = "termination_or_withdrawal", -1, 0.80
        evidence = _excerpt(combined, _TERMINATION)
        mechanism = "事项终止或撤回可能使此前正向预期失效。"
        expected = "短期预期回撤或风险偏好下降。"
        falsifiers = ["替代方案同步披露且经济效果不弱于原方案"]
    if not event_type and _REFERENCE_ONLY.search(title):
        event_type, direction, confidence = "reference_only", 0, 0.60
        evidence = _excerpt(combined, _REFERENCE_ONLY)
        mechanism = "公告事项需要规模、阶段或比较基准才能判断方向。"
        expected = "仅作解释参考，不进入排序。"
        falsifiers = ["缺少可验证规模或执行状态"]
        if _CORRECTION.search(title):
            numeric = {
                "relation_type": "correction",
                "relation_status": "unresolved",
                "relation_fact_types": _relation_fact_types(title),
                "relation_target_keys": [key]
                if (key := _earnings_relation_key(title))
                else [],
            }
    if not event_type or not evidence:
        return [], []
    if event_type == "earnings_guidance":
        relation_key = _earnings_relation_key(combined)
        if relation_key:
            numeric["event_relation_key"] = relation_key

    source_quality = 1.0 if source_verified else 0.0
    verification_state = "verified" if source_verified else "unverified"
    fact_seed = f"{source_version_id}|{event_type}|{evidence}"
    fact_id = "serfact_" + sha256(fact_seed.encode("utf-8")).hexdigest()[:24]
    claim = {
        "earnings_guidance": "公司披露了可量化的业绩方向变化。",
        "regulatory_enforcement": "公司披露了正式调查、处罚、纪律处分或监管措施。",
        "major_litigation": "公司披露了明确的重大诉讼或仲裁事项。",
        "termination_or_withdrawal": "公司披露了事项终止、撤回或取消。",
        "reference_only": "公司披露了需要进一步量化的资本或经营事项。",
    }[event_type]
    fact = SerenityFact(
        fact_id=fact_id,
        symbol=symbol,
        fact_type=event_type,
        claim=claim,
        published_at=published_at,
        effective_available_at=effective_available_at,
        source_document_id=source_document_id,
        source_version_id=source_version_id,
        source="cninfo",
        source_url=source_url,
        content_sha256=content_hash,
        direction=direction,
        confidence=confidence,
        source_quality=source_quality,
        verification_state=verification_state,
        evidence_excerpt=evidence,
        numeric_values=numeric,
        backfill_only=backfill_only,
    )
    hypothesis_id = "serhyp_" + sha256(f"{fact_id}|v1".encode()).hexdigest()[:24]
    hypothesis = SerenityHypothesis(
        hypothesis_id=hypothesis_id,
        fact_id=fact_id,
        symbol=symbol,
        event_type=event_type,
        claim=claim,
        mechanism=mechanism,
        expected_observation=expected,
        falsifiers=falsifiers,
        direction=direction,
        confidence=confidence,
        source_quality=source_quality,
        effective_available_at=effective_available_at,
        evidence_refs=[fact_id, source_document_id, source_version_id, content_hash],
        status=verification_state,
    )
    return [fact], [hypothesis]
