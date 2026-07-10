from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ..book.repo import load_run
from ..contracts.objects import EvidencePack, Judgment, MarketBook, TranscriptEvent, TurnFrame
from ..market_memory.store import load_decision_snapshot
from .context_budget import (
    ROUTING_PAYLOAD_LIMIT_BYTES,
    TOOL_EVIDENCE_PAYLOAD_LIMIT_BYTES,
    serialized_size_bytes,
)
from .market_clock import compute_market_state


_ROUTING_TEXT_LIMIT = 800
_ROUTING_CONCLUSION_LIMIT = 240
_ROUTING_REASON_LIMIT = 600
_ROUTING_SECONDARY_TEXT_LIMIT = 240
_ROUTING_CONTEXT_HEADROOM_BYTES = 50_000
_TOOL_EVIDENCE_HEADROOM_BYTES = 100_000

_HEAVY_DUPLICATE_KEYS = {
    "decision_evidence_pack",
    "explain_context",
    "feature_snapshot",
    "historical_cases",
    "nearest_cases",
    "picks",
    "ranked_board_full_context",
    "raw_bar_summary",
    "top_picks_full_context",
}


def _text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _bounded_strings(values: Any, *, count: int, text_limit: int) -> List[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return []
    return [_text(value, text_limit) for value in list(values)[:count] if str(value or "").strip()]


def _bounded_json(value: Any, *, text_limit: int = 300, max_items: int = 20, depth: int = 0) -> Any:
    if depth >= 3:
        return _text(value, text_limit)
    if isinstance(value, Mapping):
        return {
            str(key): _bounded_json(item, text_limit=text_limit, max_items=max_items, depth=depth + 1)
            for key, item in list(value.items())[:max_items]
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _bounded_json(item, text_limit=text_limit, max_items=max_items, depth=depth + 1)
            for item in list(value)[:max_items]
        ]
    if isinstance(value, str):
        return _text(value, text_limit)
    return value


def _as_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    return {}


def _pick_for(entry: Any) -> Any:
    return getattr(entry, "pick", None)


def _explain_context(entry: Any) -> Dict[str, Any]:
    pick = _pick_for(entry)
    merged = dict(getattr(pick, "explain_context", {}) or {}) if pick is not None else {}
    merged.update(dict(getattr(entry, "explain_context", {}) or {}))
    return merged


def _context_ref(entry: Any, *, run: Any = None, book: MarketBook | None = None) -> Dict[str, Any]:
    pick = _pick_for(entry)
    explain = _explain_context(entry)
    return {
        "run_id": getattr(run, "run_id", None),
        "artifact_id": (
            getattr(entry, "artifact_id", None)
            or getattr(run, "artifact_id", None)
            or getattr(book, "artifact_id", None)
        ),
        "book_version": getattr(run, "book_version", None) or getattr(book, "book_version", None),
        "decision_context_snapshot_id": (
            (getattr(pick, "decision_context_snapshot_id", None) if pick is not None else None)
            or explain.get("decision_context_snapshot_id")
        ),
        "symbol": getattr(entry, "symbol", None),
        "rank": getattr(entry, "rank", None),
    }


def _run_ref(run: Any) -> Dict[str, Any]:
    if run is None:
        return {}
    return {
        "run_id": getattr(run, "run_id", None),
        "artifact_id": getattr(run, "artifact_id", None),
        "book_version": getattr(run, "book_version", None),
        "decision_context_snapshot_id": getattr(run, "decision_context_snapshot_id", None),
    }


def _book_ref(book: MarketBook) -> Dict[str, Any]:
    return {
        "artifact_id": book.artifact_id,
        "book_version": book.book_version,
    }


def _dedupe_refs(refs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for raw in refs:
        row = {key: value for key, value in dict(raw or {}).items() if value is not None}
        if not row:
            continue
        marker = tuple(sorted(row.items()))
        if marker in seen:
            continue
        seen.add(marker)
        out.append(row)
    return out


def _candidate_summary(
    entry: Any,
    *,
    run: Any = None,
    book: MarketBook | None = None,
    text_limit: int = _ROUTING_REASON_LIMIT,
) -> Dict[str, Any]:
    pick = _pick_for(entry)
    explain = _explain_context(entry)
    risk_pack = dict(getattr(entry, "risk_pack", {}) or {})
    main_risks = explain.get("main_risks") or risk_pack.get("main_risks") or getattr(pick, "risk_flags", [])
    missing = explain.get("missing_features") or explain.get("missing_fields") or []
    take = list(getattr(entry, "take", []) or [])
    return {
        "rank": getattr(entry, "rank", None),
        "symbol": getattr(entry, "symbol", None),
        "name": getattr(entry, "name", None),
        "industry": getattr(pick, "industry", None) if pick is not None else None,
        "style_label": getattr(entry, "style_label", None) or getattr(pick, "style_label", None),
        "strategy_id": getattr(pick, "strategy_id", None) if pick is not None else None,
        "champion_strategy": getattr(entry, "champion_strategy", None) or explain.get("champion_strategy"),
        "action": getattr(entry, "action", None),
        "execution_state": getattr(entry, "execution_state", None),
        "recommendation_state": getattr(entry, "recommendation_state", None),
        "can_open": bool(getattr(entry, "can_open", False)),
        "final_score": getattr(entry, "final_score", None),
        "adaptive_score": explain.get("adaptive_score"),
        "calibrated_probability": explain.get("calibrated_probability"),
        "recommendation_strength": explain.get("recommendation_strength"),
        "entry": {
            "low": explain.get("entry_low"),
            "high": explain.get("entry_high"),
            "trigger": explain.get("trigger_price"),
        },
        "stop": explain.get("stop_price") if explain.get("stop_price") is not None else getattr(entry, "stop", None),
        "take": [value for value in (explain.get("take1"), explain.get("take2"), *take[:2]) if value is not None][:2],
        "main_risks": _bounded_strings(main_risks, count=3, text_limit=text_limit),
        "missing_features": _bounded_strings(missing, count=8, text_limit=text_limit),
        "why_selected": _text(
            getattr(pick, "why_selected", None) or getattr(pick, "thesis", None) or getattr(entry, "summary", None),
            text_limit,
        ),
        "why_ranked_here": _text(explain.get("why_ranked_here"), text_limit),
        "context_ref": _context_ref(entry, run=run, book=book),
    }


def _candidate_summaries(
    entries: Iterable[Any],
    *,
    run: Any = None,
    book: MarketBook | None = None,
    limit: int = 10,
    text_limit: int = _ROUTING_REASON_LIMIT,
) -> List[Dict[str, Any]]:
    return [
        _candidate_summary(entry, run=run, book=book, text_limit=text_limit)
        for entry in list(entries or [])[:limit]
    ]


def _run_metadata(run: Any, *, requested_run_id: str | None = None) -> Dict[str, Any]:
    if run is None:
        return {"run_id": requested_run_id, "available": False}
    return {
        "run_id": getattr(run, "run_id", requested_run_id),
        "available": True,
        "trading_day": getattr(run, "trading_day", None),
        "book_version": getattr(run, "book_version", None),
        "artifact_id": getattr(run, "artifact_id", None),
        "market_phase": getattr(run, "market_phase", None),
        "slot_status": getattr(run, "slot_status", None),
        "run_action": getattr(run, "run_action", None),
        "recommendation_state": getattr(run, "recommendation_state", None),
        "tradeable": getattr(run, "tradeable", None),
        "status_reason": _text(getattr(run, "status_reason", None) or getattr(run, "reason", None), 800),
        "no_trade_reasons": _bounded_strings(getattr(run, "no_trade_reasons", []), count=8, text_limit=400),
        "recovery_conditions": _bounded_strings(getattr(run, "recovery_conditions", []), count=8, text_limit=400),
        "decision_context_snapshot_id": getattr(run, "decision_context_snapshot_id", None),
        "candidate_count": len(list(getattr(run, "picks", []) or [])),
    }


def _run_matches_book(run: Any, book: MarketBook) -> bool:
    if run is None:
        return False
    if getattr(run, "book_version", None) and run.book_version != book.book_version:
        return False
    if getattr(run, "artifact_id", None) and run.artifact_id != book.artifact_id:
        return False
    return True


def _first_paragraph(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for separator in ("\n", "。", "！", "？"):
        if separator not in text:
            continue
        head = text.split(separator, 1)[0].strip()
        if head:
            return _text(head, _ROUTING_CONCLUSION_LIMIT)
    return _text(text, _ROUTING_CONCLUSION_LIMIT)


def _compact_turn(turn: TranscriptEvent, *, text_limit: int) -> Dict[str, Any]:
    meta = dict(getattr(turn, "meta", {}) or {})
    message = meta.get("message") if isinstance(meta.get("message"), Mapping) else {}
    narrative = message.get("narrative_text") or meta.get("narrative_text") or getattr(turn, "content", "")
    content = getattr(turn, "content", "") if getattr(turn, "role", None) == "user" else narrative
    return {
        "role": getattr(turn, "role", None),
        "content": _text(content, text_limit),
        "user_visible_conclusion": _first_paragraph(narrative) if getattr(turn, "role", None) == "assistant" else "",
        "kind": meta.get("kind"),
        "message_kind": message.get("message_kind"),
        "run_id": meta.get("run_id") or message.get("run_id"),
        "symbols": [str(symbol) for symbol in list(meta.get("symbols") or message.get("symbols") or [])[:10]],
        "symbol": message.get("symbol"),
    }


def _recent_dialogue(
    turns: Iterable[TranscriptEvent] | None,
    *,
    limit: int,
    text_limit: int,
) -> List[Dict[str, Any]]:
    return [_compact_turn(turn, text_limit=text_limit) for turn in list(turns or [])[-limit:]]


def _market_context(book: MarketBook) -> Dict[str, Any]:
    market_state = compute_market_state()
    return {
        "trading_day": book.trading_day,
        "book_version": book.book_version,
        "artifact_id": book.artifact_id,
        "slot_id": book.slot_id,
        "pulse_slot_at": book.pulse_slot_at,
        "market_phase": book.market_phase or market_state.market_phase,
        "slot_status": book.slot_status,
        "is_intraday": str(book.market_phase or "").upper() in {"INTRADAY_AM", "INTRADAY_PM", "LUNCH_BREAK"},
        "publish_allowed": book.publish_allowed,
        "gate_state": book.gate.state,
        "tradeable": book.daybook.tradeable,
        "reason": _text(book.daybook.reason, 800),
    }


def build_agent_routing_context(memory_ctx: Dict[str, Any], book: MarketBook) -> Dict[str, Any]:
    """Build the compact context used only to select the next agent tool."""

    session = memory_ctx["session"]
    turns = list(memory_ctx.get("recent_turns") or [])
    claims = list(memory_ctx.get("recent_claims") or [])
    active_run = load_run(session.active_run_id)
    previous_run = load_run(session.previous_run_id)
    candidate_summary = _candidate_summaries(book.board, run=(active_run if _run_matches_book(active_run, book) else None), book=book)

    active_meta = _run_metadata(active_run, requested_run_id=session.active_run_id)
    if active_run is not None and _run_matches_book(active_run, book):
        active_meta["candidate_source"] = "candidate_summary"
    elif active_run is not None:
        active_meta["candidate_source"] = "active_run.candidate_summary"
        active_meta["candidate_summary"] = _candidate_summaries(active_run.picks, run=active_run, book=book)
    else:
        active_meta["candidate_source"] = "unavailable"

    previous_meta = _run_metadata(previous_run, requested_run_id=session.previous_run_id)
    if previous_run is not None:
        previous_meta["candidate_source"] = "local_ref_on_demand"

    refs = [_book_ref(book), _run_ref(active_run), _run_ref(previous_run)]
    refs.extend(item["context_ref"] for item in candidate_summary)
    if isinstance(active_meta.get("candidate_summary"), list):
        refs.extend(item["context_ref"] for item in active_meta["candidate_summary"])

    context = {
        "session_has_active_run": bool(session.active_run_id),
        "session_focus_symbol": (
            session.focus_subject.get("symbol") if isinstance(session.focus_subject, Mapping) else None
        ),
        "session": {
            "session_id": session.session_id,
            "active_run_id": session.active_run_id,
            "previous_run_id": session.previous_run_id,
            "focus_subject": _bounded_json(session.focus_subject, text_limit=300, max_items=10),
            "compare_set": [str(symbol) for symbol in list(session.compare_set or [])[:10]],
            "user_preferences": _bounded_json(session.user_preferences, text_limit=300, max_items=20),
            "last_seen_book_version": session.last_seen_book_version,
            "last_focus_rank": session.last_focus_rank,
            "last_focus_symbol": session.last_focus_symbol,
        },
        "market": _market_context(book),
        "active_run": active_meta,
        "previous_run": previous_meta,
        "candidate_summary": candidate_summary,
        "recent_dialogue": _recent_dialogue(turns, limit=8, text_limit=_ROUTING_TEXT_LIMIT),
        "recent_claims": [
            {
                "subject_type": claim.subject_type,
                "subject_id": _text(claim.subject_id, 200),
                "predicate": _text(claim.predicate, 200),
                "value": _bounded_json(claim.value, text_limit=300, max_items=10),
            }
            for claim in claims[:12]
        ],
        "context_refs": _dedupe_refs(refs),
        "context_policy": {
            "shape": "agent_routing_context.v1",
            "compressed": True,
            "compression_steps": ["deduplicate_history", "summarize_candidates", "replace_blobs_with_refs"],
            "detail_expansion": "local_on_demand",
        },
    }
    if serialized_size_bytes(context) > ROUTING_PAYLOAD_LIMIT_BYTES - _ROUTING_CONTEXT_HEADROOM_BYTES:
        return compact_agent_routing_context(context)
    return context


def _compact_summary_text(summary: Dict[str, Any]) -> None:
    for key in ("why_selected", "why_ranked_here"):
        summary[key] = _text(summary.get(key), _ROUTING_SECONDARY_TEXT_LIMIT)
    for key in ("main_risks", "missing_features"):
        summary[key] = _bounded_strings(
            summary.get(key),
            count=3 if key == "main_risks" else 8,
            text_limit=_ROUTING_SECONDARY_TEXT_LIMIT,
        )


def compact_agent_routing_context(context: Dict[str, Any]) -> Dict[str, Any]:
    compacted = deepcopy(context)
    compacted["recent_dialogue"] = list(compacted.get("recent_dialogue") or [])[-4:]
    for turn in compacted["recent_dialogue"]:
        turn["content"] = _text(turn.get("content"), _ROUTING_SECONDARY_TEXT_LIMIT)
        turn["user_visible_conclusion"] = _text(
            turn.get("user_visible_conclusion"),
            _ROUTING_SECONDARY_TEXT_LIMIT,
        )
    for summary in list(compacted.get("candidate_summary") or []):
        _compact_summary_text(summary)
    active = compacted.get("active_run")
    if isinstance(active, Mapping):
        for summary in list(active.get("candidate_summary") or []):
            _compact_summary_text(summary)
    session = compacted.get("session")
    if isinstance(session, dict):
        session["user_preferences"] = _bounded_json(
            session.get("user_preferences"),
            text_limit=120,
            max_items=10,
        )
    policy = compacted.setdefault("context_policy", {})
    steps = list(policy.get("compression_steps") or [])
    steps.extend(["reduce_recent_dialogue_to_4", "truncate_summary_text_to_240"])
    policy["compression_steps"] = list(dict.fromkeys(steps))
    policy["secondary_compaction"] = True
    return compacted


def _strip_heavy_duplicates(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _strip_heavy_duplicates(item)
            for key, item in value.items()
            if str(key) not in _HEAVY_DUPLICATE_KEYS
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_strip_heavy_duplicates(item) for item in value]
    return value


def _snapshot_slice(snapshot: Dict[str, Any] | None, symbol: str) -> Dict[str, Any]:
    if not snapshot:
        return {}
    candidates = list(snapshot.get("candidate_list") or []) + list(snapshot.get("rejected_candidates") or [])
    candidate = next(
        (dict(item) for item in candidates if str((item or {}).get("symbol") or "") == symbol),
        {},
    )
    probability_output = dict(snapshot.get("probability_output") or {})
    risk_output = dict(snapshot.get("risk_output") or {})
    ranking_output = dict(snapshot.get("ranking_output") or {})
    ranking_details = dict(ranking_output.get("details") or {})
    historical_cases = dict(snapshot.get("historical_cases") or {})
    return {
        "candidate": candidate,
        "probability": probability_output.get(symbol) or {},
        "risk": risk_output.get(symbol) or {},
        "ranking": ranking_details.get(symbol) or {},
        "historical_cases": historical_cases.get(symbol) or [],
    }


def _candidate_detail(
    entry: Any,
    *,
    run: Any,
    book: MarketBook,
    source: str,
    snapshot_cache: Dict[str, Dict[str, Any] | None],
) -> Dict[str, Any]:
    pick = _pick_for(entry)
    explain = _explain_context(entry)
    ref = _context_ref(entry, run=run, book=book)
    snapshot_id = str(ref.get("decision_context_snapshot_id") or "")
    snapshot: Dict[str, Any] | None = None
    if snapshot_id:
        if snapshot_id not in snapshot_cache:
            snapshot_cache[snapshot_id] = load_decision_snapshot(snapshot_id)
        snapshot = snapshot_cache[snapshot_id]
    snapshot_evidence = _snapshot_slice(snapshot, str(getattr(entry, "symbol", "")))
    snapshot_candidate = dict(snapshot_evidence.get("candidate") or {})

    probability = dict(getattr(pick, "probability", {}) or {}) if pick is not None else {}
    risk = dict(getattr(pick, "risk", {}) or {}) if pick is not None else {}
    ranking = dict(getattr(pick, "ranking", {}) or {}) if pick is not None else {}
    historical_cases = list(getattr(pick, "historical_cases", []) or []) if pick is not None else []
    probability = probability or dict(snapshot_evidence.get("probability") or {})
    risk = risk or dict(snapshot_evidence.get("risk") or {})
    ranking = ranking or dict(snapshot_evidence.get("ranking") or {})
    historical_cases = historical_cases or list(snapshot_evidence.get("historical_cases") or [])
    if not explain and snapshot_candidate:
        explain = snapshot_candidate

    adaptive_keys = (
        "adaptive_policy",
        "adaptive_score",
        "calibrated_probability",
        "recommendation_strength",
        "adaptive_action",
        "feature_coverage",
        "expert_scores",
        "expert_contributions",
        "missing_features",
    )
    adaptive = {
        key: explain.get(key) if explain.get(key) is not None else snapshot_candidate.get(key)
        for key in adaptive_keys
        if explain.get(key) is not None or snapshot_candidate.get(key) is not None
    }
    return {
        "identity": {
            "symbol": getattr(entry, "symbol", None),
            "name": getattr(entry, "name", None),
            "rank": getattr(entry, "rank", None),
            "industry": getattr(pick, "industry", None) if pick is not None else None,
            "style_label": getattr(entry, "style_label", None) or getattr(pick, "style_label", None),
            "strategy_id": getattr(pick, "strategy_id", None) if pick is not None else None,
        },
        "decision": {
            "action": getattr(entry, "action", None),
            "execution_state": getattr(entry, "execution_state", None),
            "recommendation_state": getattr(entry, "recommendation_state", None),
            "can_open": bool(getattr(entry, "can_open", False)),
            "final_score": getattr(entry, "final_score", None),
            "live_score": getattr(entry, "live_score", None),
            "daily_rank_score": getattr(entry, "daily_rank_score", None),
            "exec_score": getattr(entry, "exec_score", None),
        },
        "plans": {
            "entry_zone": getattr(entry, "entry_zone", None),
            "stop": getattr(entry, "stop", None),
            "take": getattr(entry, "take", None),
            "entry_plan": getattr(pick, "entry_plan", {}) if pick is not None else {},
            "stop_plan": getattr(pick, "stop_plan", {}) if pick is not None else {},
            "take_profit_plan": getattr(pick, "take_profit_plan", {}) if pick is not None else {},
            "execution_plan": getattr(entry, "execution_plan", {}),
        },
        "thesis": {
            "thesis": getattr(pick, "thesis", None) if pick is not None else None,
            "why_selected": getattr(pick, "why_selected", None) if pick is not None else None,
            "why_not_others": getattr(pick, "why_not_others", []) if pick is not None else [],
            "summary": getattr(entry, "summary", None),
        },
        "signal": getattr(pick, "signal", {}) if pick is not None else {},
        "probability": probability,
        "risk": risk,
        "ranking": ranking,
        "adaptive": adaptive,
        "historical_cases": historical_cases,
        "score_breakdown": getattr(entry, "score_breakdown", {}),
        "strategy_context": getattr(entry, "strategy_context", {}),
        "risk_pack": getattr(entry, "risk_pack", {}),
        "explain_context": explain,
        "context_ref": ref,
        "evidence_sources": [source, *([f"snapshot:{snapshot_id}"] if snapshot is not None else [])],
        "snapshot_resolution": {
            "snapshot_id": snapshot_id or None,
            "loaded": snapshot is not None,
            "missing": bool(snapshot_id and snapshot is None),
            "fields_available": [
                key
                for key in ("candidate", "probability", "risk", "ranking", "historical_cases")
                if snapshot_evidence.get(key)
            ],
        },
    }


def _entry_by_symbol(entries: Iterable[Any], symbol: str) -> Any:
    for entry in list(entries or []):
        if str(getattr(entry, "symbol", "")) == symbol:
            return entry
    return None


def _run_for_entry(entry: Any, evidence: EvidencePack, judgment: Judgment) -> tuple[Any, str]:
    symbol = str(getattr(entry, "symbol", ""))
    for source, run in (
        ("judgment_run", judgment.run),
        ("active_run", evidence.active_run),
        ("previous_run", evidence.previous_run),
    ):
        if run is not None and _entry_by_symbol(getattr(run, "picks", []), symbol) is not None:
            return run, source
    return None, "current_book"


def _recommendation_entries(frame: TurnFrame, evidence: EvidencePack, judgment: Judgment) -> List[Any]:
    topk = max(1, min(10, int((frame.constraints or {}).get("topk") or 3)))
    canonical = judgment.canonical_run
    if canonical is not None:
        symbols = [str(pick.symbol) for pick in list(canonical.picks or [])[:topk]]
        source_entries = list(getattr(judgment.run, "picks", []) or []) + list(evidence.book.board or [])
        return [entry for symbol in symbols if (entry := _entry_by_symbol(source_entries, symbol)) is not None]
    if judgment.run is not None:
        return list(judgment.run.picks[:topk])
    return list(evidence.book.board[:topk])


def _target_entries(frame: TurnFrame, evidence: EvidencePack, judgment: Judgment) -> List[Any]:
    if frame.request == "recommend":
        return _recommendation_entries(frame, evidence, judgment)
    if frame.request in {"compare", "candidate_compare"}:
        return list(judgment.compare_entries or evidence.compare_entries or [])[:10]
    if judgment.subject_entry is not None:
        return [judgment.subject_entry]
    if evidence.subject_entry is not None:
        return [evidence.subject_entry]
    symbol = str((frame.references or {}).get("symbol") or "")
    if symbol:
        for entries in (
            getattr(judgment.run, "picks", []) if judgment.run is not None else [],
            getattr(evidence.active_run, "picks", []) if evidence.active_run is not None else [],
            evidence.book.board,
        ):
            entry = _entry_by_symbol(entries, symbol)
            if entry is not None:
                return [entry]
    return []


def _artifact_result(judgment: Judgment) -> Dict[str, Any]:
    for name in (
        "pick_detail",
        "single_stock_analysis",
        "live_entry",
        "no_trade",
        "exit_decision",
        "compare_view",
        "candidate_comparison",
        "intraday_situation",
        "run_change_view",
    ):
        value = getattr(judgment, name, None)
        if value is not None:
            return {"type": name, "value": _strip_heavy_duplicates(_as_dict(value))}
    if judgment.exit_view:
        return {"type": "exit_view", "value": _strip_heavy_duplicates(dict(judgment.exit_view))}
    return {}


def _judgment_result(judgment: Judgment) -> Dict[str, Any]:
    result = {
        "kind": judgment.kind,
        "summary": _text(judgment.summary, 1_200),
        "decision_action": judgment.decision_action,
        "decision_context_model": _strip_heavy_duplicates(dict(judgment.decision_context_model or {})),
        "thesis_lifecycle": dict(judgment.thesis_lifecycle or {}),
        "decision_synthesis": dict(judgment.decision_synthesis or {}),
        "evidence_refs": [str(item) for item in list(judgment.evidence_refs or [])[:20]],
        "artifact": _artifact_result(judgment),
    }
    if judgment.run is not None:
        result["run"] = _run_metadata(judgment.run)
    if judgment.canonical_run is not None:
        result["canonical_run"] = _run_metadata(judgment.canonical_run)
    return result


def _run_change_details(
    evidence: EvidencePack,
    judgment: Judgment,
    snapshot_cache: Dict[str, Dict[str, Any] | None],
) -> Dict[str, Any]:
    artifact = judgment.run_change_view
    if artifact is None:
        return {}
    symbols: List[str] = []
    symbols.extend(str(symbol) for symbol in artifact.added)
    symbols.extend(str(symbol) for symbol in artifact.removed)
    for change in artifact.rank_changes:
        symbol = str((change or {}).get("symbol") or "")
        if symbol:
            symbols.append(symbol)
    symbols = list(dict.fromkeys(symbols))[:10]
    current_run = judgment.run or evidence.active_run
    previous_run = evidence.previous_run
    current_details = []
    previous_details = []
    for symbol in symbols:
        current_entry = _entry_by_symbol(getattr(current_run, "picks", []), symbol) if current_run is not None else None
        previous_entry = _entry_by_symbol(getattr(previous_run, "picks", []), symbol) if previous_run is not None else None
        if current_entry is not None:
            current_details.append(
                _candidate_detail(
                    current_entry,
                    run=current_run,
                    book=evidence.book,
                    source="current_run",
                    snapshot_cache=snapshot_cache,
                )
            )
        if previous_entry is not None:
            previous_details.append(
                _candidate_detail(
                    previous_entry,
                    run=previous_run,
                    book=evidence.book,
                    source="previous_run",
                    snapshot_cache=snapshot_cache,
                )
            )
    return {
        "current_run": _run_metadata(current_run),
        "previous_run": _run_metadata(previous_run),
        "current_candidates": current_details,
        "previous_candidates": previous_details,
    }


def build_tool_evidence_context(
    frame: TurnFrame,
    evidence: EvidencePack,
    judgment: Judgment,
    recent_turns: List[TranscriptEvent] | None,
) -> Dict[str, Any]:
    """Expand only the locally referenced evidence needed by the selected tool."""

    snapshot_cache: Dict[str, Dict[str, Any] | None] = {}
    entries = _target_entries(frame, evidence, judgment)
    candidate_details: List[Dict[str, Any]] = []
    for entry in entries:
        run, source = _run_for_entry(entry, evidence, judgment)
        candidate_details.append(
            _candidate_detail(
                entry,
                run=run,
                book=evidence.book,
                source=source,
                snapshot_cache=snapshot_cache,
            )
        )

    run_change = _run_change_details(evidence, judgment, snapshot_cache) if frame.request == "run_change" else {}
    refs = [_book_ref(evidence.book), _run_ref(judgment.run), _run_ref(evidence.active_run), _run_ref(evidence.previous_run)]
    refs.extend(detail["context_ref"] for detail in candidate_details)
    for key in ("current_candidates", "previous_candidates"):
        refs.extend(detail["context_ref"] for detail in list(run_change.get(key) or []))

    context = {
        "frame": {
            "raw_message": frame.raw_message,
            "subject": frame.subject,
            "request": frame.request,
            "freshness": frame.freshness,
            "references": _bounded_json(frame.references, text_limit=1_000, max_items=20),
            "constraints": _bounded_json(frame.constraints, text_limit=2_000, max_items=30),
        },
        "session": {
            "session_id": evidence.session.session_id,
            "active_run_id": evidence.session.active_run_id,
            "previous_run_id": evidence.session.previous_run_id,
            "focus_subject": _bounded_json(evidence.session.focus_subject, text_limit=500, max_items=10),
            "compare_set": list(evidence.session.compare_set or [])[:10],
            "last_focus_symbol": evidence.session.last_focus_symbol,
            "last_focus_rank": evidence.session.last_focus_rank,
        },
        "market": _market_context(evidence.book),
        "runs": {
            "judgment": _run_metadata(judgment.run),
            "active": _run_metadata(evidence.active_run, requested_run_id=evidence.session.active_run_id),
            "previous": _run_metadata(evidence.previous_run, requested_run_id=evidence.session.previous_run_id),
        },
        "judgment_result": _judgment_result(judgment),
        "candidate_details": candidate_details,
        "run_change_details": run_change,
        "position_context": (
            _strip_heavy_duplicates(dict(evidence.portfolio_slice or {}))
            if frame.request == "exit_decision"
            else {}
        ),
        "recent_dialogue": _recent_dialogue(recent_turns, limit=6, text_limit=_ROUTING_TEXT_LIMIT),
        "context_refs": _dedupe_refs(refs),
        "context_policy": {
            "shape": "tool_evidence_context.v1",
            "compressed": True,
            "compression_steps": ["select_target_objects", "deduplicate_judgment", "resolve_local_refs"],
            "target_details_are_lossless": True,
        },
    }
    if serialized_size_bytes(context) > TOOL_EVIDENCE_PAYLOAD_LIMIT_BYTES - _TOOL_EVIDENCE_HEADROOM_BYTES:
        return compact_tool_evidence_context(context)
    return context


def compact_tool_evidence_context(context: Dict[str, Any]) -> Dict[str, Any]:
    compacted = deepcopy(context)
    compacted["recent_dialogue"] = []
    compacted.pop("non_target_rivals", None)
    policy = compacted.setdefault("context_policy", {})
    steps = list(policy.get("compression_steps") or [])
    steps.extend(["drop_recent_dialogue", "drop_non_target_rivals"])
    policy["compression_steps"] = list(dict.fromkeys(steps))
    policy["secondary_compaction"] = True
    return compacted
