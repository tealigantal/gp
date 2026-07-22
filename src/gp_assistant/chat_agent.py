from __future__ import annotations

"""Real-LLM chat orchestration over one immutable recommendation snapshot.

The LLM performs semantic routing and Chinese narration.  It never receives a
write-capable market tool and cannot change the snapshot's candidates, scores,
prices, actions, Serenity Alpha features, or evidence lineage.
"""

import re
import unicodedata
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable

from .agent_store import AgentStore, SnapshotIntegrityError, StoredSnapshot
from .contracts.objects import (
    AdviceRun,
    BoardEntry,
    MarketBook,
    ReplyBundle,
    SessionState,
    TranscriptEvent,
    TurnFrame,
)
from .core.errors import APIError, LLMPayloadBudgetExceeded
from .llm.client import (
    current_llm_call_trace,
    record_product_chat,
    reset_llm_call_trace,
    validate_product_llm_trace,
)
from .llm.interpret import parse_turn_frame
from .llm.narrate import render_reply
from .runtime.concern_parser import normalize_turn_frame, validate_turn_frame
from .evidence.daily_freshness import resolve_daily_target
from .runtime.market_time import compare_snapshot_market_time
from .runtime.native_snapshot import (
    native_snapshot_integrity_errors,
    pending_native_snapshot_integrity_errors,
    serenity_runtime_binding_check,
)
from .runtime.reference_resolver import inject_entity_hints, resolve_subject_and_compare
from .runtime.utils import gen_id, now_iso
from .serenity.store import (
    current_native_readiness_state,
)


_SYMBOL_RE = re.compile(r"(?<!\d)(?:60|68|00|30)\d{4}(?!\d)")
_CURRENT_OR_EXECUTION_REQUESTS = {
    "recommend",
    "single_stock_query",
    "live_entry_check",
    "exit_decision",
    "no_trade_explain",
    "candidate_compare",
    "intraday_situation",
    "chat",
}
_HISTORICAL_EXPLANATION_REQUESTS = {"term_explain", "pick_detail", "compare", "run_change"}
# Explanations are bound to the immutable session snapshot, not to the live
# scheduler revision.  A resident Serenity poll may advance while a user asks
# why an already-published candidate ranked where it did; that must not erase
# the snapshot's own evidence.  Requests that can create or alter a current
# execution judgment remain live-state-bound below.
_CURRENT_SNAPSHOT_BOUND_REQUESTS = (
    _CURRENT_OR_EXECUTION_REQUESTS | _HISTORICAL_EXPLANATION_REQUESTS
)
_LIVE_COMPARISON_MARKERS = (
    "现在",
    "当前",
    "实时",
    "此刻",
    "今天",
    "买",
    "卖",
    "入场",
    "开仓",
    "加仓",
    "减仓",
    "持有",
    "执行",
)
_SYMBOL_BOUND_REQUESTS = {
    "pick_detail",
    "single_stock_query",
    "live_entry_check",
    "compare",
    "candidate_compare",
    "intraday_situation",
    "exit_decision",
}
_NO_CANDIDATE_EVIDENCE_REASONS = {
    "native_snapshot_policy_incompatible",
    "native_snapshot_target_missing",
    "native_snapshot_alpha_incomplete",
    "native_snapshot_target_lineage_incomplete",
    "native_snapshot_candidate_outside_target",
    "new_snapshot_required_for_refresh",
    "symbol_outside_bound_snapshot",
    "position_state_unavailable_in_snapshot",
    "historical_snapshot_not_tradeable",
    "historical_snapshot_explanation_only",
    "market_data_stale",
    "market_data_unavailable",
    "market_data_invalid",
    "current_snapshot_market_time_mismatch",
    "current_serenity_target_missing",
    "current_serenity_target_replaced",
    "current_serenity_target_not_ready",
    "current_serenity_readiness_revision_missing",
    "current_serenity_readiness_revision_changed",
    "current_serenity_semantic_revision_missing",
    "current_serenity_semantic_revision_changed",
    "current_serenity_runtime_unavailable",
    "current_serenity_store_unavailable",
    "market_gate_not_allow",
}
_NUMERIC_RE = re.compile(
    r"(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?%?(?![A-Za-z0-9_])"
)
_NUMERIC_CAPTURE = r"(?P<number>(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?%?(?![A-Za-z0-9_]))"


def _is_immutable_session_explanation(
    session_snapshot: StoredSnapshot | None, frame: TurnFrame
) -> bool:
    if session_snapshot is None or frame.request not in _HISTORICAL_EXPLANATION_REQUESTS:
        return False
    if frame.request != "compare":
        return True
    raw = str(frame.raw_message or "")
    return not any(marker in raw for marker in _LIVE_COMPARISON_MARKERS)


def _number_variants(value: float, *, allow_percent: bool = False) -> set[str]:
    variants = {str(value), f"{value:g}"}
    if float(value).is_integer():
        variants.add(str(int(value)))
    if allow_percent and -1.0 <= value <= 1.0:
        percent = (Decimal(str(value)) * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        percent_text = format(percent, "f").rstrip("0").rstrip(".") or "0"
        variants.add(f"{percent_text}%")
    return variants


def _display_number(value: Any, *, digits: int) -> int | float | None:
    """Return the local, deterministic presentation value exposed to the LLM.

    The engine-owned snapshot retains full precision.  Narration receives one
    compact display projection so a model never has to choose between several
    raw/scaled versions of the same metric or invent its own rounding.
    """

    if value is None or isinstance(value, bool):
        return None
    try:
        quantum = Decimal("1") if digits == 0 else Decimal("1." + ("0" * digits))
        rounded_decimal = Decimal(str(value)).quantize(
            quantum, rounding=ROUND_HALF_UP
        )
        rounded = float(rounded_decimal)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if rounded == 0:
        rounded = 0.0
    if float(rounded).is_integer():
        return int(rounded)
    return rounded


def _allowed_numeric_tokens(value: Any, *, key: str = "") -> set[str]:
    allowed: set[str] = set()
    if isinstance(value, bool) or value is None:
        return allowed
    if isinstance(value, (int, float)):
        percent_capable = any(
            token in key.lower()
            for token in (
                "probability",
                "return",
                "confidence",
                "uncertainty",
                "rate",
                "percent",
                "pct",
            )
        )
        variants = _number_variants(float(value), allow_percent=percent_capable)
        if "contribution" in key.lower() and float(value) < 0:
            variants.update(_number_variants(abs(float(value))))
        return variants
    if isinstance(value, dict):
        for child_key, child in value.items():
            if any(token in str(child_key).lower() for token in ("hash", "_id", "refs")):
                continue
            allowed.update(_allowed_numeric_tokens(child, key=str(child_key)))
        return allowed
    if isinstance(value, list):
        for child in value:
            allowed.update(_allowed_numeric_tokens(child, key=key))
        return allowed
    numeric_string_keys = (
        "symbol", "date", "day", "time", "at", "price", "entry", "stop", "take",
        "target", "score", "probability", "return", "confidence", "uncertainty", "weight",
        "contribution", "rank", "rr", "vol", "vwap", "alpha", "value", "count", "sample",
        "coverage", "claim", "excerpt", "pct", "percent", "ratio", "change",
        "threshold",
    )
    if any(token in key.lower() for token in numeric_string_keys):
        allowed.update(_NUMERIC_RE.findall(str(value)))
    return allowed


def _allowed_market_numeric_tokens(value: Any, *, key: str = "") -> set[str]:
    """Return conservative display variants for market-level evidence.

    Market-gate metrics are descriptive, never stock-selection inputs in
    narration.  Models commonly render those supplied metrics at two or three
    decimals (and use a percent sign for change/ratio fields), so accept those
    deterministic presentation variants without loosening candidate values.
    """

    allowed: set[str] = set()
    if isinstance(value, bool) or value is None:
        return allowed
    if isinstance(value, (int, float)):
        numeric = float(value)
        allowed.update(_number_variants(numeric))
        percent_capable = any(
            token in key.lower()
            for token in ("chg", "change", "return", "ratio", "pct", "percent")
        )
        for digits in (1, 2, 3):
            rendered = f"{numeric:.{digits}f}"
            allowed.add(rendered)
            if percent_capable:
                allowed.add(f"{rendered}%")
        if percent_capable and numeric.is_integer():
            allowed.add(f"{int(numeric)}%")
        return allowed
    if isinstance(value, dict):
        for child_key, child in value.items():
            if any(token in str(child_key).lower() for token in ("hash", "_id", "refs")):
                continue
            allowed.update(_allowed_market_numeric_tokens(child, key=str(child_key)))
        return allowed
    if isinstance(value, list):
        for child in value:
            allowed.update(_allowed_market_numeric_tokens(child, key=key))
        return allowed
    allowed.update(_NUMERIC_RE.findall(str(value)))
    return allowed


_FIELD_LABEL_PATTERNS = {
    "entry_low": r"(?:entry_low|买入区间下限|入场下限|买点下限|买入低位)",
    "entry_high": r"(?:entry_high|买入区间上限|入场上限|买点上限|买入高位)",
    "trigger_price": r"(?:trigger_price|触发价|触发价格|确认价)",
    "stop_price": r"(?:stop_price|止损价|止损位|失效价|失效位)",
    # "第一目标盈亏比" is its own RR field.  Do not let its "第一目标"
    # prefix get validated as a take-profit price before the RR rule sees it.
    "take1": r"(?:take1|第一目标(?!盈亏比)|首个目标|第一止盈|止盈一|目标价|止盈价)",
    "take2": r"(?:take2|第二目标|第二止盈|止盈二)",
    "final_score": r"(?:final(?:_score)?|最终评分|最终分数|最终得分|综合评分|综合分数|综合得分|(?<!自适应)(?<!排名)(?<!排序)(?<!执行质量)(?<!数据质量)(?<!决策)(?<!实时)(?<!盘中)(?<!日线)(?<!执行)(?:评分|得分))",
    "decision_score": r"(?:decision_score|决策评分|决策分数|决策得分|决策分)",
    "live_score": r"(?:live_score|实时评分|实时分数|盘中评分|盘中分数)",
    "daily_rank_score": r"(?:daily_rank_score|日线排名分|日线排序分|日线评分)",
    "exec_score": r"(?:exec_score|执行评分|执行分数|执行分)",
    "adaptive_score": r"(?:adaptive(?:_score)?|自适应评分|自适应分数)",
    "ranking_score": r"(?:ranking_score|排名评分|排序评分|排名分数)",
    "probability": r"(?:up_probability_3d|calibrated_probability|3日上涨概率|上涨概率|上行概率|胜率|胜算)",
    "expected_return": r"(?:expected_return_3d|3日预期收益|预期收益率|预期收益|预计回报)",
    "confidence": r"(?:confidence|置信度|信心|可信度)",
    "uncertainty": r"(?:uncertainty|不确定性)",
    "effective_sample_size": r"(?:effective_sample_size|有效样本量|有效样本数)",
    "execution_quality_score": r"(?:execution_quality_score|执行质量评分|执行质量分数)",
    "risk_penalty": r"(?:risk_penalty|风险惩罚|风险扣分)",
    "data_quality_score": r"(?:data_quality_score|数据质量评分|数据质量分数)",
    "rank": r"(?:排名|位次|顺位|第\s*)",
    "alpha": r"(?:Serenity\s*)?(?:Alpha|阿尔法)(?:值)?",
    "weight": r"(?:Serenity\s*)?(?:effective_weight|权重)",
    "contribution": r"(?:Serenity\s*)?(?:score_contribution|贡献|加分|减分|调整)",
    "rr_to_take1": r"(?:rr_to_take1|第一目标盈亏比|首目标盈亏比|盈亏比)",
    "slot_rel_vol": r"(?:slot_rel_vol|时段相对量能|相对量能|量比)",
    "rs_index": r"(?:rs_index|相对指数强度|指数相对强度)",
    "rs_industry": r"(?:rs_industry|相对行业强度|行业相对强度)",
    "price_vs_vwap": r"(?:price_vs_vwap|相对VWAP位置|价格相对VWAP)",
    "vwap": r"(?:VWAP|vwap|成交量加权均价)",
    "announcement_fact_number": r"(?:官方)?公告(?:事实|披露|显示|称|记载)",
}

_RANK_RAW_NUMBER = r"(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?%?(?![A-Za-z0-9_])"
_RANK_NUMERIC_PATTERNS = (
    re.compile(
        rf"(?:排名|位次|顺位)\s*(?:为|是|：|:)?\s*"
        rf"(?P<number>{_RANK_RAW_NUMBER})(?:名|位|只|顺位)?",
        flags=re.IGNORECASE,
    ),
    re.compile(
        rf"第\s*(?P<number>{_RANK_RAW_NUMBER})(?:名|位|只|顺位)",
        flags=re.IGNORECASE,
    ),
)


def _rank_numeric_matches(text: str) -> Iterable[re.Match[str]]:
    for pattern in _RANK_NUMERIC_PATTERNS:
        yield from pattern.finditer(text)


def _numeric_values_for_keys(value: Any, keys: set[str]) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in keys and isinstance(child, (int, float)) and not isinstance(child, bool):
                found.append((normalized, child))
            found.extend(_numeric_values_for_keys(child, keys))
    elif isinstance(value, list):
        for child in value:
            found.extend(_numeric_values_for_keys(child, keys))
    return found


_FIELD_KEYS = {
    "entry_low": {"entry_low", "low"},
    "entry_high": {"entry_high", "high"},
    "trigger_price": {"trigger_price", "trigger"},
    "stop_price": {"stop_price", "stop", "price"},
    "take1": {"take1"},
    "take2": {"take2"},
    "final_score": {"final_score"},
    "decision_score": {"decision_score"},
    "live_score": {"live_score"},
    "daily_rank_score": {"daily_rank_score"},
    "exec_score": {"exec_score"},
    "adaptive_score": {"adaptive", "adaptive_score"},
    "ranking_score": {"ranking_score"},
    "probability": {"up_probability_3d", "calibrated_probability", "probability", "win_rate"},
    "expected_return": {"expected_return_3d", "expected_return"},
    "confidence": {"confidence"},
    "uncertainty": {"uncertainty"},
    "effective_sample_size": {"effective_sample_size"},
    "execution_quality_score": {"execution_quality_score"},
    "risk_penalty": {"risk_penalty"},
    "data_quality_score": {"data_quality_score"},
    "rr_to_take1": {"rr_to_take1"},
    "slot_rel_vol": {"slot_rel_vol"},
    "rs_index": {"rs_index"},
    "rs_industry": {"rs_industry"},
    "price_vs_vwap": {"price_vs_vwap"},
    "vwap": {"vwap"},
}


def _candidate_field_tokens(detail: dict[str, Any], field: str) -> set[str]:
    serenity = dict(detail.get("serenity_alpha") or {})
    execution = dict(detail.get("execution_plan") or {})
    if field == "rank":
        return _allowed_numeric_tokens(detail.get("rank"), key="rank")
    serenity_fields = {
        "alpha": ("alpha_value", "alpha"),
        "weight": ("effective_weight", "weight"),
        "contribution": ("score_contribution", "contribution"),
    }
    if field in serenity_fields:
        key, token_key = serenity_fields[field]
        value = serenity.get(key)
        tokens = _allowed_numeric_tokens(value, key=token_key)
        if field == "contribution" and isinstance(value, (int, float)):
            tokens.update(_number_variants(abs(float(value))))
        return tokens
    if field == "announcement_fact_number":
        tokens: set[str] = set()
        for fact in list(serenity.get("facts") or [])[:2]:
            if not isinstance(fact, dict):
                continue
            for key in ("claim", "evidence_excerpt"):
                tokens.update(_NUMERIC_RE.findall(str(fact.get(key) or "")))
        return tokens
    roots: list[Any]
    if field in {"entry_low", "entry_high", "trigger_price"}:
        if execution.get(field) is not None:
            roots = [{field: execution.get(field)}]
        else:
            roots = [detail.get("entry_plan") or {}]
    elif field == "stop_price":
        if execution.get("stop_price") is not None:
            roots = [{"stop_price": execution.get("stop_price")}]
        else:
            roots = [detail.get("stop_plan") or {}]
    elif field in {"take1", "take2"}:
        if execution.get(field) is not None:
            roots = [{field: execution.get(field)}]
        else:
            plan = dict(detail.get("take_profit_plan") or {})
            values = list(
                plan.get("targets")
                or plan.get("levels")
                or plan.get("take")
                or plan.get("prices")
                or []
            )
            index = 0 if field == "take1" else 1
            indexed = values[index] if len(values) > index else None
            roots = [
                {field: indexed},
                {field: plan.get(field)},
                {field: plan.get("price") if field == "take1" else None},
            ]
    elif field == "final_score":
        roots = [{"final_score": detail.get("final_score")}]
    elif field == "decision_score":
        roots = [{"decision_score": serenity.get("decision_score")}]
    elif field in {"live_score", "daily_rank_score", "exec_score"}:
        roots = [{field: detail.get(field)}]
    elif field == "adaptive_score":
        roots = [{"adaptive": (detail.get("scores") or {}).get("adaptive")}]
    else:
        roots = [
            detail.get("probability") or {},
            detail.get("risk") or {},
            detail.get("ranking") or {},
            detail.get("feature_snapshot") or {},
            detail.get("score_breakdown") or {},
            detail.get("risk_pack") or {},
            detail.get("execution_plan") or {},
            detail,
        ]
    tokens: set[str] = set()
    keys = _FIELD_KEYS.get(field, set())
    for root in roots:
        for key, value in _numeric_values_for_keys(root, keys):
            tokens.update(_allowed_numeric_tokens(value, key=key))
    readiness_field = {
        "price_vs_vwap": "price_vs_vwap",
        "slot_rel_vol": "slot_rel_vol",
        "rs_index": "rs_index",
        "rs_industry": "rs_industry",
        "rr_to_take1": "rr_to_take1",
        "data_quality_score": "data_quality",
    }.get(field)
    if readiness_field:
        readiness = dict(
            execution.get("entry_readiness")
            or (detail.get("risk_pack") or {}).get("entry_readiness")
            or {}
        )
        for check in readiness.get("checks") or []:
            if str((check or {}).get("name") or "") != readiness_field:
                continue
            tokens.update(
                _allowed_numeric_tokens((check or {}).get("current"), key=field)
            )
            tokens.update(
                _NUMERIC_RE.findall(str((check or {}).get("threshold") or ""))
            )
    return tokens


def _numeric_is_structural(
    text: str,
    match: re.Match[str],
    symbols: set[str],
) -> bool:
    token = str(match.group(0) or "")
    unsigned = token.lstrip("+-").rstrip("%")
    if unsigned in symbols:
        return True
    # A six-digit mainland security code is an entity identifier, not a price
    # or a model-authored metric.  It deliberately passes through this numeric
    # gate even when it is *not* in the scoped candidate list: the dedicated
    # symbol validator runs afterwards and decides whether the identifier is
    # permitted by the snapshot or the user's question.  Keeping those two
    # concerns separate prevents an unknown code from being reported as a
    # numeric-authority violation and lets the one-shot real-LLM repair receive
    # the actionable ``symbol_outside_snapshot`` reason.
    if _SYMBOL_RE.fullmatch(unsigned):
        return True
    before = str(text or "")[: match.start()]
    after = str(text or "")[match.end() :]
    line_prefix = before.rsplit("\n", 1)[-1]
    # A plain small positive integer may be a Markdown ordered-list marker.
    # Do not let decimals, percentages, or signed values escape the numeric
    # authority gate merely because they appear at the start of a line.
    if (
        token == unsigned
        and unsigned.isdigit()
        and 1 <= int(unsigned) <= 10
        and not line_prefix.strip()
        and re.match(r"[.)）、]\s*", after)
    ):
        return True
    # Canonical field names contain a horizon marker; that marker is a label,
    # not a model-authored probability or return value.
    if unsigned == "3" and re.match(
        r"\s*日(?:上涨概率|上行概率|预期收益|预计收益)", after
    ):
        return True
    # The product horizon is structurally fixed at 1-3 trading days.
    around = str(text or "")[max(0, match.start() - 3) : match.end() + 8]
    if unsigned in {"1", "3"} and re.search(
        r"1\s*[-—–~至到]\s*3\s*(?:个)?(?:交易)?[日天]", around
    ):
        return True
    # Permit only the digits that are actually inside a valid structural date
    # or time.  Looking merely near one can turn text such as "Top 3:600519"
    # into a false time match and accidentally authorize the candidate count.
    structural_patterns = (
        re.compile(
            r"(?<!\d)\d{4}(?:[-/]\d{1,2}(?:[-/]\d{1,2})?"
            r"|年\d{1,2}月(?:\d{1,2}日)?)(?!\d)"
        ),
        re.compile(
            r"(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d"
            r"(?::[0-5]\d)?(?!\d)"
        ),
    )
    for pattern in structural_patterns:
        for structural in pattern.finditer(str(text or "")):
            if (
                structural.start() <= match.start()
                and match.end() <= structural.end()
            ):
                return True
    return False


def _numeric_has_field_label(text: str, match: re.Match[str]) -> bool:
    start, end = match.span()
    clause_start = max(
        [text.rfind(token, 0, start) for token in "。；;，,！？!?\n【】"]
        or [-1]
    ) + 1
    following = [
        position
        for token in "。；;，,！？!?\n【】"
        if (position := text.find(token, end)) >= 0
    ]
    clause_end = min(following) if following else len(text)
    clause = text[clause_start:clause_end]
    relative_start = start - clause_start
    relative_end = end - clause_start
    raw_number = r"(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?%?(?![A-Za-z0-9_])"
    range_pattern = re.compile(
        rf"(?:买入区间|入场区间|买点区间)[^。；，,\n]{{0,12}}?"
        rf"(?P<low>{raw_number})\s*(?:-|—|–|~|至|到)\s*"
        rf"(?P<high>{raw_number})",
        flags=re.IGNORECASE,
    )
    for bound in range_pattern.finditer(clause):
        if (bound.span("low") == (relative_start, relative_end)) or (
            bound.span("high") == (relative_start, relative_end)
        ):
            return True
    for bound in _rank_numeric_matches(clause):
        if bound.span("number") == (relative_start, relative_end):
            return True
    for field, label_pattern in _FIELD_LABEL_PATTERNS.items():
        if field == "rank":
            continue
        label_matches = list(
            re.finditer(label_pattern, clause, flags=re.IGNORECASE)
        )
        for label in label_matches:
            marker = clause.find("分别", label.start())
            if marker >= 0 and relative_start > marker:
                return True
        patterns = (
            rf"{label_pattern}[^。；，,\n]{{0,18}}?{_NUMERIC_CAPTURE}",
            rf"{_NUMERIC_CAPTURE}[^。；，,\n]{{0,10}}?{label_pattern}",
        )
        for pattern in patterns:
            for bound in re.finditer(pattern, clause, flags=re.IGNORECASE):
                if bound.span("number") == (relative_start, relative_end):
                    return True
    return False


def _ordered_explicit_candidates(
    segment: str, scoped: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    positioned: list[tuple[int, dict[str, Any]]] = []
    for detail in scoped:
        positions = [
            segment.find(label)
            for label in (
                str(detail.get("symbol") or ""),
                str(detail.get("name") or ""),
            )
            if label and segment.find(label) >= 0
        ]
        if not positions:
            return []
        positioned.append((min(positions), detail))
    positioned.sort(key=lambda item: item[0])
    return [detail for _, detail in positioned]


def _validate_entry_range_binding(
    segment: str,
    scoped: list[dict[str, Any]],
    symbols: set[str],
) -> None:
    raw_number = r"(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?%?(?![A-Za-z0-9_])"
    pattern = re.compile(
        rf"(?:买入区间|入场区间|买点区间)[^。；，,\n]{{0,12}}?"
        rf"(?P<low>{raw_number})\s*(?:-|—|–|~|至|到)\s*"
        rf"(?P<high>{raw_number})",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(segment):
        low = str(match.group("low") or "")
        high = str(match.group("high") or "")
        if low.lstrip("+-").rstrip("%") in symbols or high.lstrip("+-").rstrip("%") in symbols:
            continue
        if len(scoped) != 1:
            raise RuntimeError("llm_narration_ambiguous_entry_range_numeric")
        detail = scoped[0]
        if low not in _candidate_field_tokens(detail, "entry_low"):
            raise RuntimeError(f"llm_narration_misbound_entry_low_numeric:{low}")
        if high not in _candidate_field_tokens(detail, "entry_high"):
            raise RuntimeError(f"llm_narration_misbound_entry_high_numeric:{high}")


def _validate_rank_binding(
    segment: str,
    scoped: list[dict[str, Any]],
    symbols: set[str],
) -> None:
    for match in _rank_numeric_matches(segment):
        token = str(match.group("number") or "")
        if not token or token.lstrip("+-").rstrip("%") in symbols:
            continue
        if len(scoped) != 1:
            owners = [
                detail
                for detail in scoped
                if token in _candidate_field_tokens(detail, "rank")
            ]
            if len(owners) != len(scoped):
                raise RuntimeError(
                    f"llm_narration_ambiguous_rank_numeric:{token}"
                )
            continue
        if token not in _candidate_field_tokens(scoped[0], "rank"):
            raise RuntimeError(f"llm_narration_misbound_rank_numeric:{token}")


def _validate_respective_field_binding(
    segment: str,
    scoped: list[dict[str, Any]],
    field: str,
    label_pattern: str,
    symbols: set[str],
) -> bool:
    if "分别" not in segment or len(scoped) < 2:
        return False
    label_match = re.search(label_pattern, segment, flags=re.IGNORECASE)
    if label_match is None:
        return False
    ordered = _ordered_explicit_candidates(segment, scoped)
    if len(ordered) != len(scoped):
        raise RuntimeError(f"llm_narration_ambiguous_{field}_numeric")
    marker = segment.find("分别", label_match.start())
    if marker < 0:
        return False
    suffix = segment[marker + len("分别") :]
    numeric_matches = [
        match
        for match in _NUMERIC_RE.finditer(suffix)
        if not _numeric_is_structural(suffix, match, symbols)
    ]
    if len(numeric_matches) != len(ordered):
        raise RuntimeError(f"llm_narration_ambiguous_{field}_numeric")
    for detail, match in zip(ordered, numeric_matches):
        token = str(match.group(0) or "")
        if token not in _candidate_field_tokens(detail, field):
            raise RuntimeError(
                f"llm_narration_misbound_{field}_numeric:{token}"
            )
    return True


def _segment_candidate_scope(
    segment: str,
    details: list[dict[str, Any]],
    active: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    explicit = [
        detail
        for detail in details
        if str(detail.get("symbol") or "") in segment
        or (
            str(detail.get("name") or "")
            and str(detail.get("name") or "") in segment
        )
    ]
    if not explicit:
        rank_match = re.search(r"第\s*(\d{1,2})(?:名|位|只)?", segment)
        if rank_match:
            rank = int(rank_match.group(1))
            explicit = [
                detail for detail in details if int(detail.get("rank") or 0) == rank
            ]
    if len(explicit) == 1:
        return explicit, explicit[0]
    if explicit:
        return explicit, active
    if active is not None:
        return [active], active
    if len(details) == 1:
        return details, details[0]
    return details, active


def _validate_scoped_numeric_bindings(
    text: str, details: list[dict[str, Any]]
) -> None:
    active: dict[str, Any] | None = None
    segments = re.split(
        r"(?<=[。；;，,！？!?】])|(?=【)|\n+", str(text or "")
    )
    symbols = {str(detail.get("symbol") or "") for detail in details}
    for segment in segments:
        if not segment.strip():
            continue
        scoped, active = _segment_candidate_scope(segment, details, active)
        _validate_entry_range_binding(segment, scoped, symbols)
        _validate_rank_binding(segment, scoped, symbols)
        for field, label_pattern in _FIELD_LABEL_PATTERNS.items():
            if field == "rank":
                continue
            error_field = "stop" if field == "stop_price" else field
            if _validate_respective_field_binding(
                segment, scoped, field, label_pattern, symbols
            ):
                continue
            patterns = (
                rf"{label_pattern}[^。；，,\n]{{0,18}}?{_NUMERIC_CAPTURE}",
                rf"{_NUMERIC_CAPTURE}[^。；，,\n]{{0,10}}?{label_pattern}",
            )
            for pattern in patterns:
                for match in re.finditer(pattern, segment, flags=re.IGNORECASE):
                    token = str(match.group("number") or "")
                    number_match = re.search(re.escape(token), match.group(0))
                    absolute_match = None
                    if number_match is not None:
                        absolute_match = _NUMERIC_RE.search(
                            segment,
                            match.start() + number_match.start(),
                            match.start() + number_match.end(),
                        )
                    if (
                        not token
                        or token.lstrip("+-").rstrip("%") in symbols
                        or (
                            absolute_match is not None
                            and _numeric_is_structural(
                                segment, absolute_match, symbols
                            )
                        )
                    ):
                        continue
                    if len(scoped) != 1:
                        owners = [
                            detail
                            for detail in scoped
                            if token in _candidate_field_tokens(detail, field)
                        ]
                        if len(owners) != len(scoped):
                                raise RuntimeError(
                                    f"llm_narration_ambiguous_{error_field}_numeric:{token}"
                                )
                        continue
                    if token not in _candidate_field_tokens(scoped[0], field):
                        raise RuntimeError(
                            f"llm_narration_misbound_{error_field}_numeric:{token}"
                        )


def _validate_serenity_direction_wording(
    text: str, details: list[dict[str, Any]]
) -> None:
    def asserted(segment: str, terms: tuple[str, ...]) -> bool:
        for term in terms:
            for match in re.finditer(re.escape(term), segment):
                prefix = segment[max(0, match.start() - 10) : match.start()]
                if re.search(
                    r"(?:没有|并未|未|不|无|不是|并不是)"
                    r"[^。；，,]{0,5}$",
                    prefix,
                ):
                    continue
                return True
        return False

    positive_terms = (
        "加分",
        "增益",
        "提升",
        "推高",
        "拉高",
        "抬高",
        "抬升",
        "上升",
        "增加",
        "改善",
        "正向",
        "正贡献",
        "助推",
        "推动推荐",
    )
    negative_terms = (
        "减分",
        "扣分",
        "拖累",
        "削弱",
        "压低",
        "下调",
        "负向",
        "负贡献",
        "降低排名",
    )
    active: dict[str, Any] | None = None
    segments = re.split(r"(?<=[。；;，,！？!?])|\n+", str(text or ""))
    for segment in segments:
        if not segment.strip():
            continue
        scoped, active = _segment_candidate_scope(segment, details, active)
        if not any(
            token in segment
            for token in (
                "Serenity",
                "Alpha",
                "阿尔法",
                "第九专家",
                "公告",
                "新闻",
            )
        ):
            continue
        for detail in scoped:
            contribution = float(
                (detail.get("serenity_alpha") or {}).get("score_contribution")
                or 0.0
            )
            if contribution < -1e-12 and asserted(segment, positive_terms):
                raise RuntimeError("llm_narration_reverses_serenity_contribution")
            if contribution > 1e-12 and asserted(segment, negative_terms):
                raise RuntimeError("llm_narration_reverses_serenity_contribution")


def _validate_sizing_authority(text: str) -> None:
    permitted_reminder = "控制仓位和风险"
    checked = str(text or "").replace(permitted_reminder, "")
    if re.search(
        r"(?:[一二三四五六七八九十两]+成(?:仓|仓位)?|"
        r"(?:半仓|满仓|轻仓|重仓|底仓|试仓)|"
        r"(?:小仓位|小仓|微仓|少量资金|低比例|小比例)|"
        r"(?:分批|少量)(?:买入|买进|建仓|开仓|介入|配置|投入)|"
        r"仓位\s*(?:为|是|控制在|控制为|约|建议)?\s*"
        r"(?:\d+(?:\.\d+)?%|[一二三四五六七八九十两]+成)|"
        r"\d+(?:\.\d+)?%\s*(?:的)?仓位)",
        checked,
    ):
        raise RuntimeError("llm_narration_invents_position_sizing")


def _validate_narration_authority(text: str, context: dict[str, Any]) -> None:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    _validate_sizing_authority(normalized)
    # Candidate fields remain the only numeric authority for stock claims.
    # The compact market certificate may also support an exact market-level
    # statement, but cannot be borrowed as a candidate-specific value.
    candidate_allowed = _allowed_numeric_tokens(
        context.get("candidate_details") or []
    )
    market_allowed = _allowed_market_numeric_tokens(context.get("market") or {})
    market_allowed.update(
        _allowed_market_numeric_tokens(context.get("judgment_result") or {})
    )
    allowed = candidate_allowed | market_allowed
    symbols = {
        str(detail.get("symbol") or "")
        for detail in (context.get("candidate_details") or [])
        if str(detail.get("symbol") or "")
    }
    invented: list[str] = []
    for match in _NUMERIC_RE.finditer(normalized):
        token = match.group(0)
        if _numeric_is_structural(normalized, match, symbols):
            continue
        if token not in allowed:
            invented.append(token)
            continue
        if not _numeric_has_field_label(normalized, match) and token not in market_allowed:
            invented.append(token)
    if invented:
        raise RuntimeError(f"llm_narration_contains_unbound_numeric:{','.join(invented[:5])}")

    details = list(context.get("candidate_details") or [])
    _validate_scoped_numeric_bindings(normalized, details)
    _validate_serenity_direction_wording(normalized, details)


def _serenity_payload(entry: BoardEntry) -> dict[str, Any]:
    return dict(
        (entry.pick.explain_context or {}).get("serenity")
        or (entry.pick.meta or {}).get("serenity")
        or {}
    )


def _entry_payload(entry: BoardEntry) -> dict[str, Any]:
    pick = entry.pick
    return {
        "symbol": entry.symbol,
        "name": entry.name or pick.name,
        "rank": entry.rank,
        "final_score": entry.final_score,
        "live_score": entry.live_score,
        "daily_rank_score": entry.daily_rank_score,
        "exec_score": entry.exec_score,
        "action": entry.action,
        "execution_state": entry.execution_state,
        "can_open": bool(entry.can_open),
        "invalidated": bool(entry.invalidated),
        "recommendation_state": entry.recommendation_state,
        "summary": entry.summary,
        "entry_plan": pick.entry_plan or entry.entry_zone,
        "stop_plan": pick.stop_plan or ({"price": entry.stop} if entry.stop is not None else {}),
        "take_profit_plan": pick.take_profit_plan or ({"prices": entry.take} if entry.take else {}),
        "scores": dict(pick.scores or {}),
        "probability": dict(pick.probability or {}),
        "risk": dict(pick.risk or {}),
        "ranking": dict(pick.ranking or {}),
        "vwap": entry.vwap,
        "rs_index": entry.rs_index,
        "rs_industry": entry.rs_industry,
        "slot_rel_vol": entry.slot_rel_vol,
        "feature_snapshot": dict(entry.feature_snapshot or {}),
        "score_breakdown": dict(entry.score_breakdown or {}),
        "risk_pack": dict(entry.risk_pack or {}),
        "execution_plan": dict(entry.execution_plan or {}),
        "risk_flags": list(dict.fromkeys([*pick.risk_flags, *entry.reason_codes])),
        "why_selected": pick.why_selected,
        "evidence_refs": list(
            dict.fromkeys([*pick.evidence_refs, str(entry.artifact_id or "")])
        ),
        "serenity_alpha": _serenity_payload(entry),
    }


def _narration_entry_payload(entry: BoardEntry) -> dict[str, Any]:
    """Project one immutable candidate into a compact narration certificate.

    Full engine payloads contain raw feature vectors, repeated score scales and
    many historical rows.  They remain available in the immutable snapshot and
    API response, but are a poor LLM authority surface: a model can innocently
    pick a low-level value or round it differently.  This projection is built
    locally from the same entry, keeps only user-relevant fields, and fixes the
    display precision before any provider call.
    """

    raw = _entry_payload(entry)
    execution = dict(raw.get("execution_plan") or {})
    entry_plan = dict(raw.get("entry_plan") or {})
    stop_plan = dict(raw.get("stop_plan") or {})
    take_plan = dict(raw.get("take_profit_plan") or {})
    probability = dict(raw.get("probability") or {})
    probability_evidence = dict(probability.get("evidence") or {})
    score_breakdown = dict(raw.get("score_breakdown") or {})
    risk_pack = dict(raw.get("risk_pack") or {})
    ranking = dict(raw.get("ranking") or {})
    serenity = dict(raw.get("serenity_alpha") or {})
    lineage = dict(serenity.get("lineage") or {})

    entry_low = execution.get("entry_low")
    if entry_low is None:
        entry_low = entry_plan.get("low", entry_plan.get("price"))
    entry_high = execution.get("entry_high")
    if entry_high is None:
        entry_high = entry_plan.get("high", entry_plan.get("price"))
    stop_price = execution.get("stop_price")
    if stop_price is None:
        stop_price = stop_plan.get("price")
    take1 = execution.get("take1")
    if take1 is None:
        take1 = take_plan.get("price")
        if take1 is None:
            targets = list(
                take_plan.get("targets")
                or take_plan.get("levels")
                or take_plan.get("prices")
                or []
            )
            take1 = targets[0] if targets else None
    take2 = execution.get("take2")
    if take2 is None:
        targets = list(
            take_plan.get("targets")
            or take_plan.get("levels")
            or take_plan.get("prices")
            or []
        )
        take2 = targets[1] if len(targets) > 1 else None

    compact_facts: list[dict[str, Any]] = []
    for item in list(serenity.get("facts") or [])[:2]:
        if not isinstance(item, dict):
            continue
        compact_facts.append(
            {
                key: item.get(key)
                for key in (
                    "fact_id",
                    "claim",
                    "evidence_excerpt",
                    "source",
                    "published_at",
                    "effective_available_at",
                    "learning_eligible",
                    "backfill_only",
                )
                if item.get(key) is not None
            }
        )

    raw_readiness = dict(
        execution.get("entry_readiness")
        or risk_pack.get("entry_readiness")
        or {}
    )
    readiness_checks: list[dict[str, Any]] = []
    readiness_by_name: dict[str, Any] = {}
    allowed_readiness_names = {
        "price_vs_vwap",
        "slot_rel_vol",
        "rs_index",
        "rs_industry",
        "rr_to_take1",
        "data_quality",
    }
    for raw_check in list(raw_readiness.get("checks") or []):
        if not isinstance(raw_check, dict):
            continue
        name = str(raw_check.get("name") or "")
        if name not in allowed_readiness_names:
            continue
        digits = 2 if name in {"rr_to_take1", "data_quality"} else 4
        current = raw_check.get("current")
        if isinstance(current, (int, float)) and not isinstance(current, bool):
            current = _display_number(current, digits=digits)
        check = {
            "name": name,
            "current": current,
            "threshold": raw_check.get("threshold"),
            "passed": raw_check.get("passed"),
        }
        readiness_checks.append(check)
        readiness_by_name[name] = current

    return {
        "symbol": raw.get("symbol"),
        "name": raw.get("name"),
        "rank": raw.get("rank"),
        "final_score": _display_number(raw.get("final_score"), digits=2),
        "live_score": _display_number(raw.get("live_score"), digits=2),
        "daily_rank_score": _display_number(
            raw.get("daily_rank_score"), digits=2
        ),
        "exec_score": _display_number(raw.get("exec_score"), digits=2),
        "action": raw.get("action"),
        "execution_state": raw.get("execution_state"),
        "can_open": bool(raw.get("can_open")),
        "invalidated": bool(raw.get("invalidated")),
        "recommendation_state": raw.get("recommendation_state"),
        "summary": raw.get("summary"),
        "entry_plan": {
            "entry_low": _display_number(entry_low, digits=2),
            "entry_high": _display_number(entry_high, digits=2),
        },
        "stop_plan": {
            "stop_price": _display_number(stop_price, digits=2),
            "invalidation": stop_plan.get("invalidation")
            or stop_plan.get("text")
            or execution.get("invalidation_reason"),
        },
        "take_profit_plan": {
            "take1": _display_number(take1, digits=2),
            "take2": _display_number(take2, digits=2),
        },
        "scores": {
            "adaptive": _display_number(
                (raw.get("scores") or {}).get("adaptive"), digits=4
            ),
        },
        "probability": {
            "up_probability_3d": _display_number(
                probability.get("up_probability_3d"), digits=4
            ),
            "expected_return_3d": _display_number(
                probability.get("expected_return_3d"), digits=4
            ),
            "confidence": _display_number(
                probability.get("confidence"), digits=4
            ),
            "uncertainty": _display_number(
                probability.get("uncertainty"), digits=4
            ),
            "effective_sample_size": _display_number(
                probability_evidence.get("effective_sample_size"), digits=1
            ),
        },
        "ranking": {
            "ranking_score": _display_number(
                ranking.get("ranking_score"), digits=4
            ),
        },
        "execution_quality_score": _display_number(
            score_breakdown.get("execution_quality_score"), digits=2
        ),
        "risk_penalty": _display_number(
            score_breakdown.get("risk_penalty"), digits=2
        ),
        "data_quality_score": _display_number(
            score_breakdown.get("data_quality_score"), digits=2
        ),
        "vwap": _display_number(raw.get("vwap"), digits=2),
        "rs_index": _display_number(raw.get("rs_index"), digits=4),
        "rs_industry": _display_number(raw.get("rs_industry"), digits=4),
        "slot_rel_vol": _display_number(raw.get("slot_rel_vol"), digits=4),
        "price_vs_vwap": readiness_by_name.get("price_vs_vwap"),
        "execution_plan": {
            "entry_low": _display_number(entry_low, digits=2),
            "entry_high": _display_number(entry_high, digits=2),
            "trigger_price": _display_number(
                execution.get("trigger_price"), digits=2
            ),
            "stop_price": _display_number(stop_price, digits=2),
            "take1": _display_number(take1, digits=2),
            "take2": _display_number(take2, digits=2),
            "rr_to_take1": _display_number(
                execution.get("rr_to_take1"), digits=2
            ),
            "signal_valid_until_slot": execution.get("signal_valid_until_slot"),
            "triggered": bool(execution.get("triggered")),
            "confirmation_conditions": list(
                execution.get("confirmation_conditions") or []
            )[:4],
            "invalidation_reason": execution.get("invalidation_reason"),
            "entry_readiness": {
                "ready": raw_readiness.get("ready"),
                "checks": readiness_checks,
            },
        },
        "risk_flags": list(raw.get("risk_flags") or [])[:8],
        "serenity_alpha": {
            "alpha_value": _display_number(
                serenity.get("alpha_value"), digits=4
            ),
            "decision_score": _display_number(
                serenity.get("decision_score"), digits=4
            ),
            "effective_weight": _display_number(
                serenity.get("effective_weight"), digits=4
            ),
            "score_contribution": _display_number(
                serenity.get("score_contribution"), digits=4
            ),
            "status": serenity.get("status"),
            "policy_state": serenity.get("policy_state"),
            "non_binding": bool(serenity.get("non_binding")),
            "learning_eligible": bool(serenity.get("learning_eligible")),
            "fact_ids": list(serenity.get("fact_ids") or [])[:2],
            "facts": compact_facts,
            "lineage": {
                key: lineage.get(key)
                for key in (
                    "target_id",
                    "source_run_id",
                    "readiness_revision",
                    "poll_finished_at",
                    "poll_expires_at",
                    "coverage_window_start",
                    "coverage_window_end",
                )
                if lineage.get(key) is not None
            },
        },
    }


def _provider_value_token(index: int) -> str:
    letters = ""
    number = int(index) + 1
    while number > 0:
        number, remainder = divmod(number - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return f"[[GPVAL_{letters}]]"


_PROVIDER_FIELD_LABELS = {
    "rank": "排名",
    "entry_low": "买入区间下限",
    "entry_high": "买入区间上限",
    "trigger_price": "触发价",
    "stop_price": "止损价",
    "take1": "第一目标",
    "take2": "第二目标",
    "final_score": "最终分数",
    "decision_score": "决策分",
    "live_score": "实时评分",
    "daily_rank_score": "日线排名分",
    "exec_score": "执行分",
    "adaptive_score": "自适应评分",
    "ranking_score": "排名评分",
    "up_probability_3d": "3日上涨概率",
    "expected_return_3d": "3日预期收益",
    "confidence": "置信度",
    "uncertainty": "不确定性",
    "effective_sample_size": "有效样本量",
    "execution_quality_score": "执行质量评分",
    "risk_penalty": "风险惩罚",
    "data_quality_score": "数据质量评分",
    "rr_to_take1": "第一目标盈亏比",
    "slot_rel_vol": "相对量能",
    "rs_index": "指数相对强度",
    "rs_industry": "行业相对强度",
    "price_vs_vwap": "价格相对VWAP",
    "vwap": "VWAP",
    "alpha_value": "Serenity Alpha值",
    "effective_weight": "Serenity权重",
    "score_contribution": "Serenity贡献",
    "announcement_fact_number": "公告披露",
}

_PROVIDER_KEY_FIELDS = {
    "adaptive": "adaptive_score",
    **{
        field: field
        for field in _PROVIDER_FIELD_LABELS
        if field != "announcement_fact_number"
    },
}

_PROVIDER_READINESS_FIELDS = {
    "price_vs_vwap": "price_vs_vwap",
    "slot_rel_vol": "slot_rel_vol",
    "rs_index": "rs_index",
    "rs_industry": "rs_industry",
    "rr_to_take1": "rr_to_take1",
    "data_quality": "data_quality_score",
}

_PROVIDER_FIELD_ALIASES = {
    "up_probability_3d": "probability",
    "expected_return_3d": "expected_return",
    "alpha_value": "alpha",
    "effective_weight": "weight",
    "score_contribution": "contribution",
}


def _provider_adjacent_label_pattern(field: str) -> str:
    alias = _PROVIDER_FIELD_ALIASES.get(field, field)
    if alias == "alpha":
        return r"(?:alpha_value|Serenity\s*Alpha值|Alpha值|阿尔法值)"
    return _FIELD_LABEL_PATTERNS[alias]


def _provider_canonical_field(key: str, container: Any) -> str | None:
    if key in {"claim", "evidence_excerpt"}:
        return "announcement_fact_number"
    if key in {"current", "threshold"} and isinstance(container, dict):
        return _PROVIDER_READINESS_FIELDS.get(str(container.get("name") or ""))
    return _PROVIDER_KEY_FIELDS.get(str(key or ""))


def _provider_display_text(value: int | float, *, key: str) -> str:
    percent_capable = any(
        token in str(key or "").lower()
        for token in (
            "probability",
            "return",
            "confidence",
            "uncertainty",
            "rate",
            "percent",
            "pct",
        )
    )
    numeric = float(value)
    if percent_capable and -1.0 <= numeric <= 1.0:
        percent = (Decimal(str(value)) * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        text = format(percent, "f").rstrip("0").rstrip(".") or "0"
        return f"{text}%"
    if numeric.is_integer():
        return str(int(numeric))
    return str(value)


def _provider_narration_context(
    context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    """Expose the compact certificate directly to the narration provider.

    The downstream authority validator still binds every numeric claim to a
    candidate and canonical field.  Giving the model the display values avoids
    rejecting otherwise grounded natural Chinese solely because it did not
    reproduce an internal placeholder token.
    """

    provider_context = deepcopy(context)
    policy = dict(provider_context.get("context_policy") or {})
    policy.update(
        {
            "numeric_output_protocol": "exact_candidate_certificate.v1",
            "provider_may_render_exact_bound_numeric": True,
        }
    )
    provider_context["context_policy"] = policy
    return provider_context, {}


_PROVIDER_VALUE_TOKEN_RE = re.compile(r"\[\[GPVAL_[A-Z]+\]\]")
_PROVIDER_TOKEN_CONNECTOR_RE = r"(?:\s|的|为|是|：|:|约|值|参考|=)*"


def _provider_token_clause(text: str, start: int, end: int) -> str:
    clause_start = max(
        [text.rfind(token, 0, start) for token in "。；;，,！？!?\n"]
        or [-1]
    ) + 1
    following = [
        position
        for token in "。；;，,！？!?\n"
        if (position := text.find(token, end)) >= 0
    ]
    clause_end = min(following) if following else len(text)
    return text[clause_start:clause_end]


def _validate_provider_token_binding(
    text: str,
    match: re.Match[str],
    binding: dict[str, str],
    context: dict[str, Any],
) -> None:
    clause = _provider_token_clause(text, match.start(), match.end())
    symbol = str(binding.get("symbol") or "")
    details = list(context.get("candidate_details") or [])
    explicit_symbols = {
        str(detail.get("symbol") or "")
        for detail in details
        if str(detail.get("symbol") or "") in clause
        or (
            str(detail.get("name") or "")
            and str(detail.get("name") or "") in clause
        )
    }
    if explicit_symbols and symbol not in explicit_symbols:
        raise RuntimeError("llm_narration_value_token_candidate_mismatch")

    token_index = clause.find(match.group(0))
    before = clause[:token_index]
    after = clause[token_index + len(match.group(0)) :]
    nearby_fields: set[str] = set()
    for candidate_field in _PROVIDER_FIELD_LABELS:
        alias = _PROVIDER_FIELD_ALIASES.get(candidate_field, candidate_field)
        label_pattern = _provider_adjacent_label_pattern(candidate_field)
        if re.search(
            rf"{label_pattern}{_PROVIDER_TOKEN_CONNECTOR_RE}$",
            before,
            flags=re.IGNORECASE,
        ) or re.match(
            rf"^{_PROVIDER_TOKEN_CONNECTOR_RE}{label_pattern}",
            after,
            flags=re.IGNORECASE,
        ):
            nearby_fields.add(alias)
    field = str(binding.get("field") or "")
    field_alias = _PROVIDER_FIELD_ALIASES.get(field, field)
    if nearby_fields and field_alias not in nearby_fields:
        raise RuntimeError(
            "llm_narration_value_token_field_mismatch:"
            f"{field_alias}:{','.join(sorted(nearby_fields))}"
        )


def _resolve_provider_value_tokens(
    text: str,
    token_bindings: dict[str, dict[str, str]],
    context: dict[str, Any] | None = None,
) -> str:
    raw = str(text or "")
    normalized_token_text = unicodedata.normalize("NFKC", raw)
    exact_tokens = list(_PROVIDER_VALUE_TOKEN_RE.finditer(raw))
    token_stripped = _PROVIDER_VALUE_TOKEN_RE.sub("", raw)
    if (
        "GPVAL" in normalized_token_text.upper()
        and "GPVAL" in unicodedata.normalize("NFKC", token_stripped).upper()
    ):
        raise RuntimeError("llm_narration_value_token_malformed")
    if len({match.group(0) for match in exact_tokens}) != len(exact_tokens):
        raise RuntimeError("llm_narration_value_token_reused")
    for match in exact_tokens:
        token = match.group(0)
        if token not in token_bindings:
            raise RuntimeError("llm_narration_unknown_value_token")
        if context is not None:
            _validate_provider_token_binding(
                raw, match, token_bindings[token], context
            )

    protocol_text = raw
    for token, binding in token_bindings.items():
        label_pattern = _provider_adjacent_label_pattern(
            str(binding.get("field") or "")
        )
        escaped_token = re.escape(token)
        protocol_text = re.sub(
            rf"{label_pattern}{_PROVIDER_TOKEN_CONNECTOR_RE}{escaped_token}",
            token,
            protocol_text,
            flags=re.IGNORECASE,
        )
        protocol_text = re.sub(
            rf"{escaped_token}{_PROVIDER_TOKEN_CONNECTOR_RE}{label_pattern}",
            token,
            protocol_text,
            flags=re.IGNORECASE,
        )

    resolved = protocol_text
    for token, binding in token_bindings.items():
        display = str(binding.get("display") or "")
        symbol = str(binding.get("symbol") or "")
        label = str(binding.get("label") or "")
        capsule = f"【{symbol}·{label} {display}】" if symbol else f"【{label} {display}】"
        resolved = resolved.replace(token, capsule)
    if "GPVAL" in unicodedata.normalize("NFKC", resolved).upper():
        raise RuntimeError("llm_narration_value_token_malformed")
    return resolved


def _transcript_events(session_id: str, turns: Iterable[dict[str, Any]]) -> list[TranscriptEvent]:
    events: list[TranscriptEvent] = []
    for item in turns:
        events.append(
            TranscriptEvent(
                seq=int(item.get("seq") or 0),
                turn_id=str(item.get("turn_id") or gen_id("turn")),
                session_id=session_id,
                role=str(item.get("role") or "user"),
                content=str(item.get("content") or ""),
                created_at=str(item.get("created_at") or now_iso()),
                meta=dict(item.get("payload") or {}),
            )
        )
    return events


def _session_state(
    session_id: str,
    snapshot: StoredSnapshot,
    turns: list[dict[str, Any]],
) -> SessionState:
    created_at = str(turns[0].get("created_at")) if turns else now_iso()
    updated_at = str(turns[-1].get("created_at")) if turns else created_at
    last_symbols: list[str] = []
    for turn in reversed(turns):
        if turn.get("role") != "assistant":
            continue
        payload = dict(turn.get("payload") or {})
        last_symbols = [str(item) for item in payload.get("symbols") or [] if str(item)]
        if last_symbols:
            break
    focus = last_symbols[0] if last_symbols else None
    return SessionState(
        session_id=session_id,
        created_at=created_at,
        updated_at=updated_at,
        active_run_id=snapshot.snapshot_id,
        focus_subject=(
            {"type": "symbol", "symbol": focus} if focus else {"type": "run", "run_id": snapshot.snapshot_id}
        ),
        compare_set=last_symbols[:3],
        last_candidate_symbols=last_symbols,
        last_seen_book_version=snapshot.snapshot_id,
        last_turn_id=str(turns[-1].get("turn_id")) if turns else None,
        active_run_daybook_effective_day=snapshot.daybook_effective_day,
        active_run_pulse_trade_day=snapshot.pulse_trade_day,
        active_run_pulse_slot_at=snapshot.pulse_slot_closed_at,
        last_focus_symbol=focus,
    )


def _routing_context(
    snapshot: StoredSnapshot,
    book: MarketBook,
    session: SessionState,
    turns: list[TranscriptEvent],
) -> dict[str, Any]:
    return {
        "session": {
            "session_id": session.session_id,
            "active_snapshot_id": snapshot.snapshot_id,
            "last_focus_symbol": session.last_focus_symbol,
            "compare_set": list(session.compare_set),
            "last_candidate_symbols": list(session.last_candidate_symbols),
        },
        "active_run": {
            "snapshot_id": snapshot.snapshot_id,
            "decision": snapshot.decision,
            "tradeable": snapshot.tradeable,
            "decision_trade_day": snapshot.decision_trade_day,
            "daybook_effective_day": snapshot.daybook_effective_day,
            "observed_at": snapshot.observed_at,
            "market_phase": snapshot.market_phase,
        },
        "previous_run": None,
        # Routing receives no candidate facts.  Candidate evidence is supplied
        # only after the server has validated the resolved request.
        "candidate_summary": [],
        "market": {
            "trading_day": book.trading_day,
            "market_phase": book.market_phase,
            "gate": book.gate.model_dump(mode="json"),
            "data_quality": book.data_quality.model_dump(mode="json"),
            "daybook_reason": book.daybook.reason,
        },
        "recent_dialogue": [
            {"role": item.role, "content": item.content[:500]} for item in turns[-6:]
        ],
        "routing_policy": {
            "llm_routes_only": True,
            "selection_is_immutable": True,
            "network_market_tools_available": False,
        },
    }


def _build_run(session_id: str, snapshot: StoredSnapshot, book: MarketBook) -> AdviceRun:
    return AdviceRun(
        run_id=snapshot.snapshot_id,
        session_id=session_id,
        book_version=book.book_version,
        created_at=snapshot.created_at,
        trading_day=book.trading_day,
        regime=dict(book.regime or {}),
        tradeable=bool(snapshot.tradeable),
        reason=book.daybook.reason,
        picks=list(book.board),
        evidence_refs=[str(book.artifact_id or book.book_version)],
        artifact_id=book.artifact_id,
        slot_id=book.slot_id,
        slot_status=book.slot_status,
        publish_allowed=book.publish_allowed,
        daybook_effective_day=book.daybook_effective_day,
        pulse_trade_day=book.pulse_trade_day,
        pulse_slot_at=book.pulse_slot_at,
        market_phase=book.market_phase,
        data_status=book.data_status,
        gate_state=book.gate.state,
        gate_reasons=list(book.gate.reasons),
        recommendation_state=("TRADING_SIGNAL" if snapshot.tradeable else "NO_TRADE"),
        data_quality=book.data_quality.model_dump(mode="json"),
        decision_context_snapshot_id=str(book.daybook.source_meta.get("decision_context_snapshot_id") or "") or None,
    )


def _is_historical(snapshot: StoredSnapshot, current: StoredSnapshot | None) -> bool:
    return bool(
        current is not None
        and snapshot.snapshot_id != current.snapshot_id
    )


def _current_market_time_state(snapshot: StoredSnapshot) -> dict[str, Any]:
    try:
        target = resolve_daily_target(allow_probe=False)
    except Exception as exc:
        return {
            "matches": False,
            "revision": "unavailable",
            "reason": f"{type(exc).__name__}:{exc}",
        }
    return compare_snapshot_market_time(snapshot, target)


def _snapshot_matches_current_market_time(snapshot: StoredSnapshot) -> bool:
    return bool(_current_market_time_state(snapshot).get("matches"))


def _current_serenity_check(
    book: MarketBook,
) -> tuple[str | None, dict[str, Any]]:
    source_meta = dict(book.daybook.source_meta or {})
    policy = dict(source_meta.get("serenity_policy_snapshot") or {})
    if (
        source_meta.get("serenity_native_ready") is not True
        and float(policy.get("applied_weight") or 0.0) == 0.0
    ):
        return None, {
            "available": False,
            "degraded_to_zero": True,
            "effective_weight": 0.0,
            "reason": "serenity_batch_incomplete",
        }
    snapshot_target_id = str(source_meta.get("serenity_target_id") or "")
    if not snapshot_target_id:
        return "current_serenity_target_missing", {}
    try:
        current = current_native_readiness_state(snapshot_target_id)
    except Exception:
        return "current_serenity_store_unavailable", {}
    return serenity_runtime_binding_check(source_meta, current)


def _current_serenity_reason(book: MarketBook) -> str | None:
    return _current_serenity_check(book)[0]


def _engine_decision(
    snapshot: StoredSnapshot,
    book: MarketBook,
    frame: TurnFrame,
    *,
    historical: bool,
    immutable_explanation: bool = False,
    market_time_state: dict[str, Any] | None = None,
    serenity_check: tuple[str | None, dict[str, Any]] | None = None,
) -> tuple[str, str]:
    integrity_errors = (
        native_snapshot_integrity_errors(snapshot, book)
        if book.daybook.source_meta.get("serenity_native_ready") is True
        or bool(book.daybook.picks)
        else pending_native_snapshot_integrity_errors(snapshot, book)
    )
    if integrity_errors:
        return "no_trade", integrity_errors[0]
    if historical:
        if frame.request in _CURRENT_OR_EXECUTION_REQUESTS:
            return "no_trade", "historical_snapshot_not_tradeable"
        return "no_trade", "historical_snapshot_explanation_only"
    if immutable_explanation:
        return "no_trade", "snapshot_explanation_only"
    if (
        frame.request in _CURRENT_SNAPSHOT_BOUND_REQUESTS
        and not immutable_explanation
        and not bool(
            (market_time_state or _current_market_time_state(snapshot)).get(
                "matches"
            )
        )
    ):
        return "no_trade", "current_snapshot_market_time_mismatch"
    if frame.freshness == "rebuild_run" or bool((frame.constraints or {}).get("require_refresh")):
        return "no_trade", "new_snapshot_required_for_refresh"
    if (
        frame.request in _CURRENT_SNAPSHOT_BOUND_REQUESTS
        and not immutable_explanation
    ):
        serenity_reason = (serenity_check or _current_serenity_check(book))[0]
        if serenity_reason:
            return "no_trade", serenity_reason
    freshness = str(book.data_quality.freshness_state or "").lower()
    if freshness in {
        "stale",
        "unavailable",
        "invalid",
        "degraded",
        "missing",
        "incomplete",
        "lagging",
        "blocked",
    }:
        return "no_trade", f"market_data_{freshness}"
    if snapshot.tradeable and (
        not bool(book.data_quality.complete)
        or freshness not in {"fresh", "current"}
    ):
        return "no_trade", "market_data_incomplete"
    if (
        frame.request != "chat"
        and str(book.gate.state or "").upper() != "ALLOW"
    ):
        return "no_trade", "market_gate_not_allow"
    if frame.request == "chat":
        return "informational", "conversation_only"
    requested_symbol = str((frame.references or {}).get("symbol") or "")
    if requested_symbol and requested_symbol not in {entry.symbol for entry in book.board}:
        return "no_trade", "symbol_outside_bound_snapshot"
    if snapshot.decision == "no_trade":
        return "no_trade", str(book.daybook.source_meta.get("decision_reason") or book.daybook.reason or "selection_no_trade")
    if frame.request == "exit_decision":
        return "no_trade", "position_state_unavailable_in_snapshot"
    if frame.request == "live_entry_check" and snapshot.tradeable:
        requested = str((frame.references or {}).get("symbol") or "")
        entry = next((item for item in book.board if item.symbol == requested), None)
        if entry is None or not entry.can_open:
            return "no_trade", "snapshot_entry_not_open"
    if not snapshot.tradeable:
        return "recommend", "next_session_plan"
    return "recommend", "snapshot_tradeable"


def _target_entries(
    frame: TurnFrame,
    session: SessionState,
    book: MarketBook,
) -> tuple[BoardEntry | None, list[BoardEntry], list[BoardEntry]]:
    if frame.request in _SYMBOL_BOUND_REQUESTS or frame.request in {"term_explain", "run_change"}:
        subject, compared = resolve_subject_and_compare(
            frame=frame,
            session=session,
            book=book,
            active_entries=list(book.board),
        )
    else:
        subject, compared = None, []
    if frame.request == "recommend":
        topk = max(1, min(10, int((frame.constraints or {}).get("topk") or 3)))
        targets = list(book.board[:topk])
    elif frame.request in {"compare", "candidate_compare"}:
        targets = compared or list(book.board[:2])
    elif subject is not None:
        targets = [subject]
    elif frame.request in {"no_trade_explain", "run_change"}:
        targets = list(book.board[:3])
    else:
        targets = []
    return subject, compared, targets


def _message_kind(frame: TurnFrame, decision: str) -> str:
    if frame.request == "chat":
        return "chat"
    if decision != "recommend" and frame.request not in _HISTORICAL_EXPLANATION_REQUESTS:
        return "no_trade"
    return {
        "candidate_compare": "compare",
        "single_stock_query": "pick_detail",
        "live_entry_check": "pick_detail",
        "exit_decision": "exit_decision",
        "term_explain": "pick_detail",
    }.get(frame.request, frame.request)


def _selection_meta_summary(
    book: MarketBook, *, decision: str, reason: str
) -> dict[str, Any]:
    meta = dict(book.daybook.source_meta or {})
    policy = dict(meta.get("serenity_policy_snapshot") or {})
    return {
        "decision": str(meta.get("decision") or decision),
        "decision_reason": reason,
        "selection_policy": str(meta.get("selection_policy") or ""),
        "decision_context_snapshot_id": str(
            meta.get("decision_context_snapshot_id") or ""
        ),
        "serenity_native_ready": meta.get("serenity_native_ready") is True,
        "serenity_formula_version": str(
            meta.get("serenity_formula_version") or ""
        ),
        "serenity_target_id": str(meta.get("serenity_target_id") or ""),
        "serenity_source_run_id": str(
            meta.get("serenity_source_run_id") or ""
        ),
        "serenity_readiness_revision": str(
            meta.get("serenity_readiness_revision") or ""
        ),
        "serenity_semantic_revision": str(
            meta.get("serenity_semantic_revision") or ""
        ),
        "serenity_poll_finished_at": str(
            meta.get("serenity_poll_finished_at") or ""
        ),
        "serenity_poll_expires_at": str(
            meta.get("serenity_poll_expires_at") or ""
        ),
        "serenity_policy": {
            "mode": str(policy.get("mode") or ""),
            "state": str(policy.get("state") or ""),
            "epoch": int(policy.get("epoch") or 0),
            "native_required": policy.get("native_required") is True,
        },
        "candidate_universe": dict(meta.get("candidate_universe") or {}),
    }


def _narration_context(
    frame: TurnFrame,
    snapshot: StoredSnapshot,
    book: MarketBook,
    session: SessionState,
    turns: list[TranscriptEvent],
    decision: str,
    reason: str,
    targets: list[BoardEntry],
    *,
    historical: bool,
    immutable_explanation: bool = False,
) -> dict[str, Any]:
    historical_explanation = bool(
        (historical or immutable_explanation)
        and frame.request in _HISTORICAL_EXPLANATION_REQUESTS
    )
    candidate_evidence_blocked = bool(
        frame.request == "chat"
        or (
            not historical_explanation
            and (
                reason in _NO_CANDIDATE_EVIDENCE_REASONS
                or reason.startswith("native_snapshot_")
                or reason.startswith("current_serenity_")
                or reason.startswith("market_data_")
                or reason.startswith("candidate_universe_")
                or reason.startswith("legacy_coverage_")
            )
        )
    )
    if candidate_evidence_blocked:
        details = []
    else:
        details = targets or (list(book.board[:5]) if decision == "no_trade" else [])
    selection_meta = (
        {
            "decision": "no_trade" if decision != "informational" else decision,
            "decision_reason": reason,
            "candidate_evidence_redacted": True,
        }
        if candidate_evidence_blocked
        else _selection_meta_summary(book, decision=decision, reason=reason)
    )
    return {
        "frame": frame.model_dump(mode="json"),
        "session": {
            "session_id": session.session_id,
            "active_snapshot_id": snapshot.snapshot_id,
            "last_focus_symbol": session.last_focus_symbol,
        },
        "market": {
            "trading_day": book.trading_day,
            "market_phase": book.market_phase,
            "gate": book.gate.model_dump(mode="json"),
            "data_quality": book.data_quality.model_dump(mode="json"),
            "candidate_universe": dict(book.candidate_universe or {}),
            "universe_quality": dict(book.universe_quality or {}),
        },
        "judgment_result": {
            "decision": decision,
            "reason": reason,
            "tradeable": bool(decision == "recommend" and snapshot.tradeable),
            "historical": bool(historical or immutable_explanation),
            "explanation_only": bool(historical_explanation),
            "snapshot_id": snapshot.snapshot_id,
            "decision_trade_day": snapshot.decision_trade_day,
            "daybook_effective_day": snapshot.daybook_effective_day,
            "observed_at": snapshot.observed_at,
            "daybook_reason": book.daybook.reason,
            "selection_meta": selection_meta,
        },
        "candidate_details": [
            _narration_entry_payload(entry) for entry in details
        ],
        "recent_dialogue": [
            {"role": item.role, "content": item.content[:800]} for item in turns[-6:]
        ],
        "context_policy": {
            "shape": "snapshot_llm_evidence.v2",
            "snapshot_only": True,
            "selection_and_numbers_immutable": True,
            "numbers_are_local_display_projection": True,
            "numeric_values_must_be_copied_exactly": True,
            "serenity_is_native_precomputed_alpha": True,
            "no_fallback_response": True,
            "snapshot_explanation_only": bool(immutable_explanation),
            "candidate_evidence_blocked": candidate_evidence_blocked,
            "compression_steps": ["snapshot_only", "target_candidates", "recent_six_turns"],
        },
    }


def _allowed_evidence_refs(entries: list[BoardEntry]) -> list[str]:
    refs: list[str] = []
    for entry in entries:
        refs.extend(str(item) for item in entry.pick.evidence_refs if str(item))
        refs.extend(
            str(item)
            for item in (_serenity_payload(entry).get("fact_ids") or [])
            if str(item)
        )
    return list(dict.fromkeys(refs))


def _validate_narrated_symbols(
    text: str, allowed_symbols: Iterable[str], raw_message: str
) -> None:
    allowed = {str(symbol) for symbol in allowed_symbols if str(symbol)}
    allowed.update(_SYMBOL_RE.findall(raw_message or ""))
    invented = set(_SYMBOL_RE.findall(text or "")) - allowed
    if invented:
        raise RuntimeError("llm_narration_contains_symbol_outside_snapshot")


def run_chat_turn(
    *,
    session_id: str | None,
    client_turn_id: str,
    user_message: str,
    store: AgentStore | None = None,
) -> dict[str, Any]:
    """Route, narrate, validate and atomically commit one snapshot-bound turn."""

    store = store or AgentStore()
    resolved_session_id = session_id or gen_id("session")
    prior = store.assistant_turn_payload(
        resolved_session_id,
        client_turn_id,
        user_content=user_message,
    )
    if prior is not None:
        return prior
    reset_llm_call_trace()

    session_snapshot = store.session_snapshot(resolved_session_id)
    current_snapshot = store.current_snapshot()
    snapshot = session_snapshot or current_snapshot
    if snapshot is None:
        raise APIError(
            status_code=503,
            message="当前没有可验证的推荐快照",
            detail={"reason": "current_snapshot_unavailable"},
        )
    book = store.book_for_snapshot(snapshot)

    stored_turns = store.session_turns(resolved_session_id)
    transcript = _transcript_events(resolved_session_id, stored_turns)
    session = _session_state(resolved_session_id, snapshot, stored_turns)
    try:
        frame = parse_turn_frame(
            _routing_context(snapshot, book, session, transcript),
            user_message,
        )
        frame = normalize_turn_frame(frame, book=book)
        frame = inject_entity_hints(frame, {"session": session}, book)
        frame = normalize_turn_frame(frame, book=book)
        frame = validate_turn_frame(frame)

        subject, compared, targets = _target_entries(frame, session, book)
        historical = _is_historical(snapshot, current_snapshot)
        immutable_explanation = _is_immutable_session_explanation(
            session_snapshot, frame
        )
        initial_market_time_state = (
            _current_market_time_state(snapshot)
            if not historical
            and not immutable_explanation
            and frame.request in _CURRENT_SNAPSHOT_BOUND_REQUESTS
            else None
        )
        initial_serenity_check = (
            _current_serenity_check(book)
            if not historical
            and not immutable_explanation
            and frame.request in _CURRENT_SNAPSHOT_BOUND_REQUESTS
            else None
        )
        decision, reason = _engine_decision(
            snapshot,
            book,
            frame,
            historical=historical,
            immutable_explanation=immutable_explanation,
            market_time_state=initial_market_time_state,
            serenity_check=initial_serenity_check,
        )
        narration_context = _narration_context(
            frame,
            snapshot,
            book,
            session,
            transcript,
            decision,
            reason,
            targets,
            historical=historical,
            immutable_explanation=immutable_explanation,
        )
    except Exception as ex:
        record_product_chat(success=False, stage="routing_or_engine", error=ex)
        raise
    provider_narration_context, provider_value_tokens = (
        _provider_narration_context(narration_context)
    )
    try:
        reply_text = render_reply(
            {"tool_evidence_context": provider_narration_context}
        )
    except (APIError, LLMPayloadBudgetExceeded) as ex:
        record_product_chat(success=False, stage="narration", error=ex)
        raise
    except Exception as ex:  # noqa: BLE001
        record_product_chat(success=False, stage="narration", error=ex)
        raise APIError(
            status_code=502,
            message="LLM 解释生成失败",
            detail={"reason": f"{type(ex).__name__}:{ex}"},
        ) from ex
    if not str(reply_text or "").strip():
        record_product_chat(success=False, stage="narration_empty", error=RuntimeError("llm_narration_empty"))
        raise APIError(
            status_code=502,
            message="LLM 解释为空",
            detail={"reason": "llm_narration_empty"},
        )

    explanation_details = bool(
        frame.request in _HISTORICAL_EXPLANATION_REQUESTS
        and decision == "no_trade"
        and (historical or immutable_explanation)
    )
    candidate_evidence_blocked = bool(
        narration_context["context_policy"].get("candidate_evidence_blocked")
    )
    output_entries = (
        targets
        if not candidate_evidence_blocked
        and (decision == "recommend" or explanation_details)
        else []
    )
    picks = [_entry_payload(entry) for entry in output_entries]
    symbols = [entry.symbol for entry in output_entries]
    kind = _message_kind(frame, decision)
    evidence_refs = _allowed_evidence_refs(output_entries)
    run = _build_run(resolved_session_id, snapshot, book)
    if immutable_explanation:
        run = run.model_copy(
            update={
                "tradeable": False,
                "publish_allowed": False,
                "recommendation_state": "NO_TRADE",
                "reason": "snapshot_explanation_only",
            }
        )
    if candidate_evidence_blocked:
        run = run.model_copy(
            update={
                "tradeable": False,
                "picks": [],
                "recommendation_state": "NO_TRADE",
            }
        )
    message = {
        "message_kind": kind,
        "snapshot_id": snapshot.snapshot_id,
        "as_of": snapshot.as_of,
        "tradeable": bool(decision == "recommend" and snapshot.tradeable),
        "reason": reason,
        "decision_reason": reason,
        "intent": frame.model_dump(mode="json"),
        "picks": picks,
        "perspective": (
            "historical"
            if historical or immutable_explanation
            else "blocked_current"
            if candidate_evidence_blocked
            else "current"
        ),
        "is_current": bool(
            not historical
            and not immutable_explanation
            and not candidate_evidence_blocked
        ),
        "risk_notice": "A 股市场存在损失风险；该结果是短期决策信息，不构成保证收益。",
    }
    reply_bundle = ReplyBundle(
        session_id=resolved_session_id,
        text=reply_text,
        kind=kind,
        run_id=snapshot.snapshot_id,
        symbols=symbols,
        message=message,
        evidence_refs=evidence_refs,
        tool_trace={"frame": frame.model_dump(mode="json"), "source": "real_llm"},
    )
    def projected_bundle(text: str) -> tuple[ReplyBundle, str]:
        resolved_text = _resolve_provider_value_tokens(
            text, provider_value_tokens, narration_context
        )
        candidate_bundle = reply_bundle.model_copy(update={"text": resolved_text})
        return candidate_bundle, resolved_text

    # The complete post-generation narration validation/repair layer is
    # temporarily disabled. The immutable snapshot remains authoritative for
    # the structured decision, tradeability and candidate fields.
    reply_bundle, reply_text = projected_bundle(reply_text)

    claims = [
        {
            "claim_id": gen_id("claim"),
            "type": "snapshot_pick",
            "symbol": pick["symbol"],
            "snapshot_id": snapshot.snapshot_id,
            "evidence_refs": pick["evidence_refs"],
        }
        for pick in picks
    ]
    llm_trace = current_llm_call_trace()
    try:
        validate_product_llm_trace(llm_trace)
    except Exception as ex:  # noqa: BLE001
        record_product_chat(success=False, stage="llm_trace_validation", error=ex)
        raise APIError(
            status_code=502,
            message="LLM 调用证据未通过完整性校验",
            detail={"reason": f"{type(ex).__name__}:{ex}"},
        ) from ex
    payload = {
        "session_id": resolved_session_id,
        "client_turn_id": client_turn_id,
        "snapshot_id": snapshot.snapshot_id,
        "decision": decision,
        "reply": reply_text,
        "message": message,
        "symbols": symbols,
        "llm_trace": llm_trace,
    }
    expected_current_snapshot_id = None
    if (
        not historical
        and not immutable_explanation
        and frame.request in _CURRENT_SNAPSHOT_BOUND_REQUESTS
    ):
        final_market_time_state = _current_market_time_state(snapshot)
        if (
            initial_market_time_state is None
            or final_market_time_state.get("revision")
            != initial_market_time_state.get("revision")
            or bool(final_market_time_state.get("matches"))
            != bool(initial_market_time_state.get("matches"))
        ):
            ex = SnapshotIntegrityError(
                "current_market_time_changed_before_commit"
            )
            record_product_chat(
                success=False,
                stage="precommit_market_time_revalidation",
                error=ex,
            )
            raise ex
        final_serenity_check = _current_serenity_check(book)
        initial_serenity_reason, initial_serenity_state = (
            initial_serenity_check or (None, {})
        )
        final_serenity_reason, final_serenity_state = final_serenity_check
        if (
            final_serenity_reason != initial_serenity_reason
            or str(final_serenity_state.get("semantic_revision") or "")
            != str(initial_serenity_state.get("semantic_revision") or "")
            or str(final_serenity_state.get("binding_token") or "")
            != str(initial_serenity_state.get("binding_token") or "")
            or bool(final_serenity_state.get("available"))
            != bool(initial_serenity_state.get("available"))
        ):
            ex = SnapshotIntegrityError(
                "current_serenity_state_changed_before_commit"
            )
            record_product_chat(
                success=False,
                stage="precommit_serenity_revalidation",
                error=ex,
            )
            raise ex
        expected_current_snapshot_id = snapshot.snapshot_id
    try:
        committed = store.commit_turn(
            session_id=resolved_session_id,
            client_turn_id=client_turn_id,
            user_content=user_message,
            assistant_content=reply_text,
            assistant_payload=payload,
            snapshot_id=snapshot.snapshot_id,
            claims=claims,
            expected_current_snapshot_id=expected_current_snapshot_id,
        )
    except Exception as ex:
        record_product_chat(success=False, stage="atomic_commit", error=ex)
        raise
    record_product_chat(success=True, stage="committed", trace=llm_trace)
    return committed
