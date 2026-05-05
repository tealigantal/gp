from __future__ import annotations

from typing import List, Optional

from ..contracts.objects import (
    BoardEntry,
    CanonicalPick,
    CompareArtifact,
    EvidencePack,
    ExitDecisionArtifact,
    Judgment,
    LiveEntryDecisionArtifact,
    NoTradeArtifact,
    PickDetailArtifact,
    RunChangeArtifact,
)
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
    )


def _stale_live_entry(run, pick: CanonicalPick, message: str) -> LiveEntryDecisionArtifact:
    return LiveEntryDecisionArtifact(
        symbol=pick.symbol,
        name=pick.name,
        execution_state="UNAVAILABLE",
        can_execute_now=False,
        next_action="先补齐该标的日线，再重新检查 5 分钟入场结构。",
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
    )


def recommend_workflow(session_id: str, evidence: EvidencePack, *, topk: int) -> Judgment:
    run = publish_run(session_id=session_id, book=evidence.book, topk=topk)
    canonical_run = build_canonical_run(book=evidence.book, run=run, picks=run.picks)
    if canonical_run.run_action == "NO_TRADE":
        no_trade = build_no_trade_view(canonical_run, evidence.book)
        return Judgment(
            kind="no_trade",
            summary=no_trade.status_reason,
            run=run,
            canonical_run=canonical_run,
            no_trade=no_trade,
            compare_entries=run.picks,
            evidence_refs=[evidence.book.book_version, run.run_id],
        )
    return Judgment(
        kind="recommend",
        summary=canonical_run.status_reason or "已生成当前计划。",
        run=run,
        canonical_run=canonical_run,
        compare_entries=run.picks,
        evidence_refs=[evidence.book.book_version, run.run_id],
    )


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
    return Judgment(
        kind="pick_detail",
        summary=detail.why_selected or detail.thesis,
        run=run,
        canonical_run=canonical_run,
        subject_entry=evidence.subject_entry,
        pick_detail=detail,
        evidence_refs=[evidence.book.book_version, evidence.subject_entry.symbol],
    )


def no_trade_workflow(evidence: EvidencePack) -> Judgment:
    run = evidence.active_run or publish_run(session_id=evidence.session.session_id, book=evidence.book, topk=max(3, len(evidence.book.board)))
    canonical_run = build_canonical_run(book=evidence.book, run=run, picks=run.picks)
    no_trade = build_no_trade_view(canonical_run, evidence.book)
    return Judgment(
        kind="no_trade",
        summary=no_trade.status_reason,
        run=run,
        canonical_run=canonical_run,
        subject_entry=evidence.subject_entry,
        no_trade=no_trade,
        evidence_refs=[evidence.book.book_version, run.run_id],
    )


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
    live_entry = _stale_live_entry(canonical_run, pick, freshness_issue) if freshness_issue else build_live_entry_view(canonical_run, pick)
    return Judgment(
        kind="live_entry_check",
        summary=live_entry.summary,
        run=run,
        canonical_run=canonical_run,
        subject_entry=evidence.subject_entry,
        live_entry=live_entry,
        evidence_refs=[evidence.book.book_version, evidence.subject_entry.symbol],
    )


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
    return Judgment(
        kind="compare",
        summary=(compare_view.comparison_points[0] if compare_view.comparison_points else "已完成比较。"),
        run=run,
        canonical_run=canonical_run,
        compare_entries=entries,
        compare_view=compare_view,
        evidence_refs=[evidence.book.book_version, run.run_id],
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
    return Judgment(
        kind="exit_decision",
        summary=exit_view.reason,
        run=run,
        canonical_run=canonical_run,
        subject_entry=evidence.subject_entry,
        exit_decision=exit_view,
        exit_view=exit_view.model_dump(),
        evidence_refs=[evidence.book.book_version, evidence.subject_entry.symbol],
    )


def run_change_workflow(evidence: EvidencePack) -> Judgment:
    diff = build_run_change_view(evidence.active_run, evidence.previous_run)
    return Judgment(
        kind="run_change",
        summary="已比较本轮与上轮推荐变化。",
        run=evidence.active_run,
        subject_entry=None,
        run_change_view=diff,
        diff=diff.model_dump(),
        evidence_refs=[evidence.book.book_version, *([evidence.active_run.run_id] if evidence.active_run else [])],
    )
