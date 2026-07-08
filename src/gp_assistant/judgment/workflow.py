from __future__ import annotations

from typing import Any, List, Optional

from ..contracts.objects import (
    BoardEntry,
    CanonicalPick,
    CandidateComparisonArtifact,
    CompareArtifact,
    EvidencePack,
    ExitDecisionArtifact,
    IntradaySituationArtifact,
    Judgment,
    LiveEntryDecisionArtifact,
    NoTradeArtifact,
    PickDetailArtifact,
    RunChangeArtifact,
)
from ..decision_engine.intelligence import enrich_pick_with_synthesis, objective_from_frame, synthesize_decision
from ..evidence.live_quote_service import build_live_quote_snapshot
from ..evidence.single_stock_service import analyze_single_stock
from ..runtime.canonical_artifact import (
    build_canonical_pick,
    build_canonical_run,
    build_compare_view,
    build_exit_view,
    build_live_entry_view,
    build_no_trade_view,
    build_pick_detail_view,
    build_run_change_view,
)
from .publish import publish_run


def _pick_from_run(judgment_run, book, symbol: str | None = None, rank: int | None = None) -> Optional[CanonicalPick]:
    if judgment_run is None:
        return None
    canonical_run = build_canonical_run(book=book, run=judgment_run, picks=judgment_run.picks)
    for pick in canonical_run.picks:
        if symbol and pick.symbol == symbol:
            return pick
        if rank is not None and pick.rank == rank:
            return pick
    return canonical_run.picks[0] if canonical_run.picks else None


def _pick_freshness_issue(pick: CanonicalPick | None) -> str | None:
    if pick is None:
        return None
    provenance = dict(pick.data_provenance or {})
    freshness_state = str(provenance.get("daily_freshness_state") or "").strip().lower()
    last_date = str(provenance.get("daily_last_date") or "").strip()
    if freshness_state and freshness_state != "current":
        suffix = f"（当前日线截止 {last_date}）" if last_date else ""
        return f"该标的日线未补齐到目标交易日，当前不输出正式交易判断{suffix}。"
    return None


def _stale_pick_detail(run, pick: CanonicalPick, message: str) -> PickDetailArtifact:
    return PickDetailArtifact(
        symbol=pick.symbol,
        name=pick.name,
        rank=pick.rank,
        thesis=message,
        why_selected=message,
        entry_text=pick.entry_text,
        stop_text=pick.stop_text,
        take_text=pick.take_text,
        invalidation=pick.invalidation,
        execution_state="UNAVAILABLE",
        risk_level="high",
        reason_codes=[*list(pick.reason_codes or []), "daily_freshness_blocked"],
        data_provenance=pick.data_provenance,
        source_run_id=(run.run_id if run else None),
        explain_context=pick.explain_context,
    )


def _stale_live_entry(run, pick: CanonicalPick, message: str) -> LiveEntryDecisionArtifact:
    return LiveEntryDecisionArtifact(
        symbol=pick.symbol,
        name=pick.name,
        execution_state="UNAVAILABLE",
        can_execute_now=False,
        next_action="先补齐该标的日线，再重新检查日线入场结构。",
        summary=message,
        gate_state=(run.gate.get("state") if run and isinstance(run.gate, dict) else None),
        gate_reasons=list(run.gate.get("reasons") or []) if run and isinstance(run.gate, dict) else [],
        vwap=pick.vwap,
        orb30_high=pick.orb30_high,
        orb30_low=pick.orb30_low,
        entry_text=pick.entry_text,
        stop_text=pick.stop_text,
        take_text=pick.take_text,
        entry_distance_pct=pick.entry_distance_pct,
        slot_rel_vol=pick.slot_rel_vol,
        rs_index=pick.rs_index,
        rs_industry=pick.rs_industry,
        reason_codes=[*list(pick.reason_codes or []), "daily_freshness_blocked"],
        data_provenance=pick.data_provenance,
        source_run_id=(run.run_id if run else None),
        explain_context=pick.explain_context,
    )


def _stale_exit(run, pick: CanonicalPick, message: str) -> ExitDecisionArtifact:
    return ExitDecisionArtifact(
        symbol=pick.symbol,
        action="WATCH",
        reason=message,
        trigger="等待该标的日线补齐后再给正式处理建议",
        stop=pick.stop,
        invalidation=pick.invalidation,
        take_profit=pick.take_profit,
        current_state="UNAVAILABLE",
        confidence=0.2,
        source_run_id=(run.run_id if run else None),
        data_provenance=pick.data_provenance,
    )


def _stale_compare(run, picks: List[CanonicalPick], stale_points: List[str]) -> CompareArtifact:
    return CompareArtifact(
        compared_symbols=[pick.symbol for pick in picks],
        leader_symbol=None,
        ranking=[
            {
                "symbol": pick.symbol,
                "rank": pick.rank,
                "execution_state": "UNAVAILABLE",
                "final_score": pick.final_score,
                "live_score": pick.live_score,
                "risk_level": "high",
            }
            for pick in picks
        ],
        comparison_points=stale_points,
        source_run_id=(run.run_id if run else None),
        data_provenance=(run.data_provenance if run else {}),
        explain_context={"ranking_context": [pick.explain_context for pick in picks if pick.explain_context]},
    )


def _synthesis(
    evidence: EvidencePack,
    *,
    run=None,
    pick: CanonicalPick | None = None,
    candidates: List[CanonicalPick] | None = None,
    objective: str | None = None,
    extra_constraints: dict | None = None,
) -> dict:
    return synthesize_decision(
        evidence=evidence,
        run=run,
        pick=pick,
        candidates=candidates or [],
        objective=objective or objective_from_frame(evidence.frame),
        extra_constraints=extra_constraints or {},
    )


def _artifact_with_synthesis(artifact, synthesis: dict):
    return artifact.model_copy(
        update={
            "decision_context_model": dict(synthesis.get("decision_context_model") or {}),
            "thesis_lifecycle": dict(synthesis.get("thesis_lifecycle") or {}),
            "decision_synthesis": dict(synthesis.get("decision_synthesis") or {}),
            "decision_action": str(synthesis.get("decision_action") or "WAIT"),
        }
    )


def _judgment_with_synthesis(judgment: Judgment, synthesis: dict) -> Judgment:
    return judgment.model_copy(
        update={
            "decision_context_model": dict(synthesis.get("decision_context_model") or {}),
            "thesis_lifecycle": dict(synthesis.get("thesis_lifecycle") or {}),
            "decision_synthesis": dict(synthesis.get("decision_synthesis") or {}),
            "decision_action": str(synthesis.get("decision_action") or "WAIT"),
        }
    )


def _enrich_run_decisions(evidence: EvidencePack, canonical_run, *, objective: str | None = None):
    picks = list(getattr(canonical_run, "picks", []) or [])
    enriched: List[CanonicalPick] = []
    synthesis_rows: List[dict] = []
    for pick in picks:
        synthesis = _synthesis(evidence, run=canonical_run, pick=pick, candidates=picks, objective=objective or "open_or_add_position")
        enriched_pick = enrich_pick_with_synthesis(pick, synthesis)
        enriched.append(enriched_pick)
        synthesis_rows.append(
            {
                "symbol": pick.symbol,
                "action": synthesis.get("decision_action"),
                "thesis_state": (synthesis.get("thesis_lifecycle") or {}).get("current_thesis_state"),
                "confidence": (synthesis.get("decision_synthesis") or {}).get("confidence"),
            }
        )
    pack = dict(getattr(canonical_run, "decision_evidence_pack", {}) or {})
    if synthesis_rows:
        pack["decision_intelligence"] = synthesis_rows
    run_synthesis = _synthesis(evidence, run=canonical_run, pick=(enriched[0] if enriched else None), candidates=enriched, objective=objective or objective_from_frame(evidence.frame))
    return canonical_run.model_copy(
        update={
            "picks": enriched,
            "decision_evidence_pack": pack,
            "decision_context_model": dict(run_synthesis.get("decision_context_model") or {}),
            "thesis_lifecycle": dict(run_synthesis.get("thesis_lifecycle") or {}),
            "decision_action": str(run_synthesis.get("decision_action") or "WAIT"),
            "decision_synthesis": dict(run_synthesis.get("decision_synthesis") or {}),
        }
    )


def _single_stock_proxy_pick(analysis) -> dict[str, Any]:
    trade_plan = dict(getattr(analysis, "trade_plan", {}) or {})
    diagnostics = dict(trade_plan.get("diagnostics") or {})
    champion = dict(getattr(analysis, "champion", {}) or {})
    state = str(getattr(analysis, "overall_state", "") or "UNAVAILABLE")
    reason_codes = [str(item) for item in list(getattr(analysis, "reason_codes", []) or [])]
    thesis = f"单票日线状态为 {state}。"
    if champion:
        thesis = f"单票日线状态为 {state}，候选策略 {champion.get('strategy') or 'NA'}。"
    return {
        "symbol": getattr(analysis, "symbol", None),
        "name": getattr(analysis, "name", None),
        "rank": None,
        "action": "WATCH",
        "execution_state": state,
        "recommendation_state": state,
        "can_execute_now": state == "PLAN_READY",
        "thesis": thesis,
        "why_selected": thesis,
        "entry_text": trade_plan.get("entry_text") or diagnostics.get("entry_text"),
        "stop_text": trade_plan.get("stop_text") or diagnostics.get("stop_text"),
        "take_text": trade_plan.get("take_text") or diagnostics.get("take_text"),
        "champion_strategy": champion.get("strategy"),
        "champion_strategy_score": champion.get("score"),
        "execution_plan": trade_plan,
        "risk_flags": reason_codes,
        "risk": {"risk_flags": reason_codes},
        "probability": {},
        "ranking": {},
        "historical_cases": [],
        "data_provenance": dict(getattr(analysis, "data_provenance", {}) or {}),
    }


def recommend_workflow(session_id: str, evidence: EvidencePack, *, topk: int) -> Judgment:
    run = publish_run(session_id=session_id, book=evidence.book, topk=topk)
    canonical_run = build_canonical_run(book=evidence.book, run=run, picks=run.picks)
    canonical_run = _enrich_run_decisions(evidence, canonical_run, objective="open_or_add_position")
    if canonical_run.run_action == "NO_TRADE":
        no_trade = build_no_trade_view(canonical_run, evidence.book)
        synthesis = _synthesis(evidence, run=canonical_run, pick=(canonical_run.picks[0] if canonical_run.picks else None), candidates=canonical_run.picks, objective="evaluate_no_trade_decision")
        no_trade = _artifact_with_synthesis(no_trade, synthesis)
        return Judgment(
            kind="no_trade",
            summary=no_trade.status_reason,
            run=run,
            canonical_run=canonical_run,
            no_trade=no_trade,
            compare_entries=run.picks,
            evidence_refs=[evidence.book.book_version, run.run_id],
            decision_context_model=dict(synthesis.get("decision_context_model") or {}),
            thesis_lifecycle=dict(synthesis.get("thesis_lifecycle") or {}),
            decision_synthesis=dict(synthesis.get("decision_synthesis") or {}),
            decision_action=str(synthesis.get("decision_action") or "NO_TRADE"),
        )
    synthesis = _synthesis(evidence, run=canonical_run, pick=(canonical_run.picks[0] if canonical_run.picks else None), candidates=canonical_run.picks, objective="open_or_add_position")
    return _judgment_with_synthesis(Judgment(
        kind="recommend",
        summary=canonical_run.status_reason or "已生成当前计划。",
        run=run,
        canonical_run=canonical_run,
        compare_entries=run.picks,
        evidence_refs=[evidence.book.book_version, run.run_id],
    ), synthesis)


def pick_detail_workflow(evidence: EvidencePack) -> Judgment:
    if evidence.subject_entry is None:
        return _missing_subject_workflow(evidence)
    run = evidence.active_run
    if run is None:
        run = publish_run(session_id=evidence.session.session_id, book=evidence.book, topk=max(3, len(evidence.book.board)))
    canonical_run = build_canonical_run(book=evidence.book, run=run, picks=run.picks)
    pick = next((item for item in canonical_run.picks if item.symbol == evidence.subject_entry.symbol), None)
    if pick is None:
        pick = build_canonical_pick(evidence.subject_entry, evidence.book)
    freshness_issue = _pick_freshness_issue(pick)
    detail = _stale_pick_detail(canonical_run, pick, freshness_issue) if freshness_issue else build_pick_detail_view(canonical_run, pick)
    synthesis = _synthesis(evidence, run=canonical_run, pick=pick, candidates=canonical_run.picks, objective="evaluate_security_decision")
    pick = enrich_pick_with_synthesis(pick, synthesis)
    detail = _artifact_with_synthesis(detail, synthesis)
    return _judgment_with_synthesis(Judgment(
        kind="pick_detail",
        summary=detail.why_selected or detail.thesis,
        run=run,
        canonical_run=canonical_run,
        subject_entry=evidence.subject_entry,
        pick_detail=detail,
        evidence_refs=[evidence.book.book_version, evidence.subject_entry.symbol],
    ), synthesis)


def single_stock_workflow(evidence: EvidencePack) -> Judgment:
    refs = evidence.frame.references or {}
    symbol = str(refs.get("symbol") or "").strip()
    analysis = analyze_single_stock(symbol, book=evidence.book)
    if analysis.data_status.get("error") == "invalid_symbol":
        summary = "未识别到有效的 6 位 A 股代码，暂不做单票分析。"
    elif analysis.overall_state == "UNAVAILABLE":
        summary = f"{analysis.symbol} 的日线数据不足，暂不输出正式交易结论。"
    elif analysis.overall_state == "STALE_OBSERVE":
        summary = f"{analysis.symbol} 只能基于未补齐到目标交易日的日线做结构观察。"
    else:
        summary = f"{analysis.symbol} 已完成日线与冠军策略分析，当前状态为 {analysis.overall_state}。"
    synthesis = _synthesis(evidence, pick=_single_stock_proxy_pick(analysis), candidates=[], objective="evaluate_security_decision")
    analysis = analysis.model_copy(
        update={
            "decision_context_model": dict(synthesis.get("decision_context_model") or {}),
            "thesis_lifecycle": dict(synthesis.get("thesis_lifecycle") or {}),
            "decision_synthesis": dict(synthesis.get("decision_synthesis") or {}),
            "decision_action": str(synthesis.get("decision_action") or "WAIT"),
        }
    )
    return _judgment_with_synthesis(Judgment(
        kind="single_stock_query",
        summary=summary,
        single_stock_analysis=analysis,
        evidence_refs=[evidence.book.book_version, analysis.symbol],
    ), synthesis)


def no_trade_workflow(evidence: EvidencePack) -> Judgment:
    run = evidence.active_run or publish_run(session_id=evidence.session.session_id, book=evidence.book, topk=max(3, len(evidence.book.board)))
    canonical_run = build_canonical_run(book=evidence.book, run=run, picks=run.picks)
    no_trade = build_no_trade_view(canonical_run, evidence.book)
    synthesis = _synthesis(evidence, run=canonical_run, pick=(canonical_run.picks[0] if canonical_run.picks else None), candidates=canonical_run.picks, objective="evaluate_no_trade_decision")
    no_trade = _artifact_with_synthesis(no_trade, synthesis)
    return _judgment_with_synthesis(Judgment(
        kind="no_trade",
        summary=no_trade.status_reason,
        run=run,
        canonical_run=canonical_run,
        subject_entry=evidence.subject_entry,
        no_trade=no_trade,
        evidence_refs=[evidence.book.book_version, run.run_id],
    ), synthesis)


def _missing_subject_message(evidence: EvidencePack) -> str:
    frame = getattr(evidence, "frame", None)
    if getattr(frame, "request", None) == "compare":
        return "当前没有足够可比较的标的，先不做强弱排序。"
    refs = getattr(frame, "references", {}) or {}
    if refs.get("rank") is not None:
        return f"当前没有可核对的第 {refs.get('rank')} 只标的，先不做单票执行判断。"
    if refs.get("symbol"):
        return f"当前计划里没有找到 {refs.get('symbol')}，先不做单票执行判断。"
    return "当前没有明确可核对的标的，先不做单票执行判断。"


def _missing_subject_workflow(evidence: EvidencePack) -> Judgment:
    base = no_trade_workflow(evidence)
    message = _missing_subject_message(evidence)
    no_trade = base.no_trade
    if no_trade is not None:
        reasons: list[str] = []
        for item in [message, *list(no_trade.no_trade_reasons or [])]:
            text = str(item or "").strip()
            if text and text not in reasons:
                reasons.append(text)
        no_trade = no_trade.model_copy(
            update={
                "market_summary": message,
                "status_reason": message,
                "no_trade_reasons": reasons[:5],
            }
        )
    return base.model_copy(
        update={
            "kind": "no_trade",
            "summary": message,
            "subject_entry": None,
            "no_trade": no_trade,
        }
    )


def live_entry_workflow(evidence: EvidencePack) -> Judgment:
    if evidence.subject_entry is None:
        return _missing_subject_workflow(evidence)
    run = evidence.active_run or publish_run(session_id=evidence.session.session_id, book=evidence.book, topk=max(3, len(evidence.book.board)))
    canonical_run = build_canonical_run(book=evidence.book, run=run, picks=run.picks)
    pick = next((item for item in canonical_run.picks if item.symbol == evidence.subject_entry.symbol), None)
    if pick is None:
        pick = build_canonical_pick(evidence.subject_entry, evidence.book)
    freshness_issue = _pick_freshness_issue(pick)
    quote_snapshot = build_live_quote_snapshot(
        symbol=evidence.subject_entry.symbol,
        user_message=evidence.frame.raw_message,
        trade_day=evidence.book.pulse_trade_day or evidence.book.trading_day,
    )
    live_entry = (
        _stale_live_entry(canonical_run, pick, freshness_issue)
        if freshness_issue
        else build_live_entry_view(canonical_run, pick, quote_snapshot=quote_snapshot)
    )
    synthesis = _synthesis(
        evidence,
        run=canonical_run,
        pick=pick,
        candidates=canonical_run.picks,
        objective="open_or_add_position",
        extra_constraints={
            "quote_snapshot": dict(live_entry.quote_snapshot or {}),
            "plan_position": dict(live_entry.plan_position or {}),
        },
    )
    pick = enrich_pick_with_synthesis(pick, synthesis)
    live_entry = _artifact_with_synthesis(live_entry, synthesis)
    return _judgment_with_synthesis(Judgment(
        kind="live_entry_check",
        summary=live_entry.summary,
        run=run,
        canonical_run=canonical_run,
        subject_entry=evidence.subject_entry,
        live_entry=live_entry,
        evidence_refs=[evidence.book.book_version, evidence.subject_entry.symbol],
    ), synthesis)


def compare_workflow(evidence: EvidencePack) -> Judgment:
    entries: List[BoardEntry] = list(evidence.compare_entries or ([] if evidence.subject_entry is None else [evidence.subject_entry]))
    if not entries and evidence.active_run is not None:
        entries = list(evidence.active_run.picks[:2])
    if not entries:
        entries = list(evidence.book.board[:2])
    if not entries:
        return _missing_subject_workflow(evidence)
    run = evidence.active_run or publish_run(session_id=evidence.session.session_id, book=evidence.book, topk=max(3, len(evidence.book.board)))
    canonical_run = build_canonical_run(book=evidence.book, run=run, picks=run.picks)
    picks = [next((item for item in canonical_run.picks if item.symbol == entry.symbol), build_canonical_pick(entry, evidence.book)) for entry in entries]
    if not picks:
        return _missing_subject_workflow(evidence)
    stale_points = [issue for issue in (_pick_freshness_issue(pick) for pick in picks) if issue]
    compare_view = _stale_compare(canonical_run, picks, stale_points) if stale_points else build_compare_view(canonical_run, picks)
    synthesis = _synthesis(evidence, run=canonical_run, pick=(picks[0] if picks else None), candidates=picks, objective="compare_alternatives")
    compare_view = _artifact_with_synthesis(compare_view, synthesis)
    return _judgment_with_synthesis(Judgment(
        kind="compare",
        summary=(compare_view.comparison_points[0] if compare_view.comparison_points else "已完成比较。"),
        run=run,
        canonical_run=canonical_run,
        compare_entries=entries,
        compare_view=compare_view,
        evidence_refs=[evidence.book.book_version, run.run_id],
    ), synthesis)


def candidate_compare_workflow(evidence: EvidencePack) -> Judgment:
    refs = dict(evidence.frame.references or {})
    constraints = dict(evidence.frame.constraints or {})
    entries: List[BoardEntry] = list(evidence.compare_entries or [])
    if not entries and evidence.active_run is not None:
        entries = list(evidence.active_run.picks)
    if not entries:
        entries = list(evidence.book.board)

    top_n = constraints.get("top_n") or constraints.get("rank_scope_top_n")
    try:
        scope_count = max(1, min(int(top_n), len(entries))) if top_n is not None else len(entries)
    except Exception:
        scope_count = len(entries)
    scoped_entries = list(entries[:scope_count])
    scope_symbols = [entry.symbol for entry in scoped_entries]

    selected_symbol = str(refs.get("selected_symbol") or refs.get("symbol") or "").strip() or None
    selected_entry = next((entry for entry in scoped_entries if entry.symbol == selected_symbol), None)
    if selected_entry is None and refs.get("rank") is not None:
        try:
            wanted_rank = int(refs.get("rank"))
        except Exception:
            wanted_rank = -1
        selected_entry = next((entry for entry in scoped_entries if int(entry.rank) == wanted_rank), None)
        if selected_entry is not None:
            selected_symbol = selected_entry.symbol
        elif wanted_rank > 0:
            raise ValueError(f"agent selected rank outside candidate scope: {wanted_rank}")
    if selected_symbol and selected_entry is None:
        raise ValueError(f"agent selected symbol outside candidate scope: {selected_symbol}")

    try:
        confidence = float(constraints.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    reason = str(constraints.get("selection_reason") or constraints.get("reason") or "").strip()
    if not reason:
        reason = "模型根据当前候选集合和用户约束完成了比较。"
    synthesis = _synthesis(
        evidence,
        run=evidence.active_run,
        pick=(build_canonical_pick(selected_entry, evidence.book) if selected_entry is not None else None),
        candidates=[build_canonical_pick(entry, evidence.book) for entry in scoped_entries],
        objective="compare_alternatives",
    )
    artifact = CandidateComparisonArtifact(
        compared_symbols=scope_symbols,
        selected_symbol=selected_symbol,
        selected_rank=(int(selected_entry.rank) if selected_entry is not None else None),
        selection_reason=reason,
        rejected_symbols=[symbol for symbol in scope_symbols if symbol != selected_symbol],
        user_constraint=str(constraints.get("user_constraint") or evidence.frame.raw_message or "").strip(),
        candidate_scope=scope_symbols,
        confidence=max(0.0, min(1.0, confidence)),
        source_run_id=(evidence.active_run.run_id if evidence.active_run else None),
        model_reasoning_summary=str(constraints.get("model_reasoning_summary") or "").strip() or None,
        decision_context_model=dict(synthesis.get("decision_context_model") or {}),
        thesis_lifecycle=dict(synthesis.get("thesis_lifecycle") or {}),
        decision_synthesis=dict(synthesis.get("decision_synthesis") or {}),
        decision_action=str(synthesis.get("decision_action") or "WAIT"),
    )
    canonical_run = build_canonical_run(book=evidence.book, run=evidence.active_run, picks=evidence.active_run.picks) if evidence.active_run else None
    return _judgment_with_synthesis(Judgment(
        kind="candidate_compare",
        summary=artifact.selection_reason,
        run=evidence.active_run,
        canonical_run=canonical_run,
        subject_entry=selected_entry,
        compare_entries=scoped_entries,
        candidate_comparison=artifact,
        evidence_refs=[evidence.book.book_version, *([evidence.active_run.run_id] if evidence.active_run else [])],
    ), synthesis)


def intraday_situation_workflow(evidence: EvidencePack) -> Judgment:
    base = live_entry_workflow(evidence)
    live_entry = base.live_entry
    quote = dict(getattr(live_entry, "quote_snapshot", {}) or {}) if live_entry is not None else {}
    user_quote = dict(quote.get("user_quote") or {})
    verified = bool(quote.get("verified"))
    source = "verified" if verified else ("unverified_user_input" if quote.get("source") == "user" else "quote_unavailable")
    symbol = (live_entry.symbol if live_entry is not None else None) or str((evidence.frame.references or {}).get("symbol") or "").strip() or None
    if live_entry is not None:
        summary = live_entry.summary
    elif base.no_trade is not None:
        summary = base.no_trade.status_reason
    else:
        summary = "盘中情况暂时没有足够可核对的标的。"
    artifact = IntradaySituationArtifact(
        symbol=symbol,
        source=source,
        verified=verified,
        user_quote=user_quote,
        quote_snapshot=quote,
        live_entry=live_entry,
        summary=summary,
        source_run_id=(base.run.run_id if base.run else None),
        decision_context_model=dict(base.decision_context_model or {}),
        thesis_lifecycle=dict(base.thesis_lifecycle or {}),
        decision_synthesis=dict(base.decision_synthesis or {}),
        decision_action=str(base.decision_action or "WAIT"),
    )
    return base.model_copy(
        update={
            "kind": "intraday_situation",
            "summary": summary,
            "intraday_situation": artifact,
        }
    )


def exit_workflow(evidence: EvidencePack) -> Judgment:
    if evidence.subject_entry is None:
        return _missing_subject_workflow(evidence)
    run = evidence.active_run or publish_run(session_id=evidence.session.session_id, book=evidence.book, topk=max(3, len(evidence.book.board)))
    canonical_run = build_canonical_run(book=evidence.book, run=run, picks=run.picks)
    pick = next((item for item in canonical_run.picks if item.symbol == evidence.subject_entry.symbol), None)
    if pick is None:
        pick = build_canonical_pick(evidence.subject_entry, evidence.book)
    freshness_issue = _pick_freshness_issue(pick)
    exit_view = _stale_exit(canonical_run, pick, freshness_issue) if freshness_issue else build_exit_view(canonical_run, pick)
    synthesis = _synthesis(evidence, run=canonical_run, pick=pick, candidates=canonical_run.picks, objective="manage_existing_position")
    pick = enrich_pick_with_synthesis(pick, synthesis)
    exit_view = _artifact_with_synthesis(exit_view, synthesis)
    return _judgment_with_synthesis(Judgment(
        kind="exit_decision",
        summary=exit_view.reason,
        run=run,
        canonical_run=canonical_run,
        subject_entry=evidence.subject_entry,
        exit_decision=exit_view,
        exit_view=exit_view.model_dump(),
        evidence_refs=[evidence.book.book_version, evidence.subject_entry.symbol],
    ), synthesis)


def run_change_workflow(evidence: EvidencePack) -> Judgment:
    diff = build_run_change_view(evidence.active_run, evidence.previous_run)
    synthesis = _synthesis(evidence, run=evidence.active_run, pick=None, candidates=[], objective="audit_previous_decision")
    diff = diff.model_copy(
        update={
            "decision_context_model": dict(synthesis.get("decision_context_model") or {}),
            "thesis_lifecycle": dict(synthesis.get("thesis_lifecycle") or {}),
            "decision_synthesis": dict(synthesis.get("decision_synthesis") or {}),
            "decision_action": str(synthesis.get("decision_action") or "WAIT"),
        }
    )
    return _judgment_with_synthesis(Judgment(
        kind="run_change",
        summary="已比较本轮与上轮推荐变化。",
        run=evidence.active_run,
        subject_entry=None,
        run_change_view=diff,
        diff=diff.model_dump(),
        evidence_refs=[evidence.book.book_version, *([evidence.active_run.run_id] if evidence.active_run else [])],
    ), synthesis)
