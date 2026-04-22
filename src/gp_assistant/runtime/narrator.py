from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..llm.narrate import render_reply
from ..contracts.objects import ReplyBundle, Judgment, TurnFrame, EvidencePack, BoardEntry, TranscriptEvent


def _to_action_and_state(entry: BoardEntry) -> tuple[str, str]:
    if entry.invalidated:
        return 'INVALID', '已失效'
    if entry.can_open:
        return 'BUY', '当前可买'
    return 'WATCH', ('等回踩' if entry.pulse and (entry.pulse.entry_distance_pct or 0) > 0 else '先观察')


def _format_or_none(text: Optional[str]) -> Optional[str]:
    t = (text or '').strip()
    return t or None


def _entry_text(plan: Dict[str, Any]) -> Optional[str]:
    if not plan:
        return None
    for key in ('text', 'desc', 'range'):
        v = _format_or_none(str(plan.get(key))) if plan.get(key) is not None else None
        if v:
            return v
    # Numeric fallback from low/high/price when textual not provided
    try:
        lo = plan.get('low'); hi = plan.get('high'); pr = plan.get('price')
        def _fmt(x):
            try:
                f = float(x)
                s = (('%f' % f).rstrip('0').rstrip('.'))
                return s or str(f)
            except Exception:
                return _format_or_none(str(x))
        if lo is not None and hi is not None:
            alo = _fmt(lo); ahi = _fmt(hi)
            if alo and ahi:
                return f"{alo} - {ahi}"
        if pr is not None:
            ap = _fmt(pr)
            if ap:
                return ap
    except Exception:
        pass
    return None


def _stop_text(plan: Dict[str, Any]) -> Optional[str]:
    if not plan:
        return None
    for key in ('text', 'desc', 'level'):
        v = _format_or_none(str(plan.get(key))) if plan.get(key) is not None else None
        if v:
            return v
    return None


def _take_text(plan: Dict[str, Any]) -> Optional[str]:
    if not plan:
        return None
    for key in ('text', 'desc', 'levels', 'targets'):
        v = _format_or_none(str(plan.get(key))) if plan.get(key) is not None else None
        if v:
            return v
    return None


def _canonical_pick(e: BoardEntry) -> Dict[str, Any]:
    action, state_label = _to_action_and_state(e)
    missing: List[str] = []
    entry_text = _entry_text(e.pick.entry_plan)
    stop_text = _stop_text(e.pick.stop_plan)
    take_text = _take_text(e.pick.take_profit_plan)
    if not entry_text:
        missing.append('entry')
    if not stop_text:
        missing.append('stop')
    if not take_text:
        missing.append('take')
    return {
        'symbol': e.symbol,
        'name': e.name,
        'rank': e.rank,
        'action': action,
        'state_label': state_label,
        'thesis': _format_or_none(e.pick.thesis),
        'entry_text': entry_text,
        'stop_text': stop_text,
        'take_text': take_text,
        'why_selected_text': _format_or_none(e.pick.why_selected),
        'reason_short': _format_or_none(e.summary),
        'can_execute_now': bool(e.can_open and not e.invalidated),
        'missing_fields': missing,
    }


def _build_canonical_message(evidence: EvidencePack, judgment: Judgment, narrative_text: str) -> Dict[str, Any]:
    freshness_meta = {
        'book_version': evidence.book.book_version,
        'daybook_effective_day': evidence.book.daybook_effective_day or evidence.book.daybook.trading_day,
        'pulse_trade_day': evidence.book.pulse_trade_day,
        'pulse_slot_at': evidence.book.pulse_slot_at,
        'market_phase': evidence.book.market_phase,
        'data_status': evidence.book.data_status,
    }
    kind = (judgment.kind or '').lower()
    if kind == 'recommend' and judgment.run is not None:
        picks = [_canonical_pick(e) for e in judgment.run.picks]
        watch_all = not any(p.get('can_execute_now') for p in picks)
        decision_state = 'BUY' if not watch_all else 'WATCH'
        followups: List[str] = []
        if len(picks) >= 2:
            a, b = picks[0]['symbol'], picks[1]['symbol']
            followups.append(f"为什么第一只是 {a}，不是第二只 {b}")
            followups.append(f"{b} 现在还能买吗")
        if picks:
            followups.append(f"看 {picks[0]['symbol']} 卖出判断")
        # Ensure narrative_text not empty and explains WATCH-all case
        nt = (narrative_text or '').strip()
        if watch_all:
            head = "这轮更偏候选观察，不是立即买入清单。当前更建议等待盘中确认（如回到计划买点或 5 分钟状态重新转强）。"
            why_first = picks[0].get('why_selected_text') or picks[0].get('reason_short') or '执行性与结构相对更优'
            tail = f"第一名 {picks[0]['symbol']} 仍排在前列，主要因为 {why_first}。"
            nt = (nt + "\n" + head + tail).strip() if nt else (head + tail)
        return {
            'message_kind': 'recommend',
            'lead_summary': judgment.summary,
            'decision_state': decision_state,
            'market_summary': evidence.book.daybook.reason or '',
            'execution_note': '',
            'risk_note': '',
            'picks': picks,
            'narrative_text': nt,
            'followup_suggestions': followups,
            'freshness_meta': freshness_meta,
        }
    if kind == 'explain':
        return {
            'message_kind': 'explain',
            'narrative_text': narrative_text,
            'state_tags': [],
            'freshness_meta': freshness_meta,
        }
    if kind == 'live_check':
        return {
            'message_kind': 'live_check',
            'narrative_text': narrative_text,
            'state_tags': [],
            'freshness_meta': freshness_meta,
        }
    if kind == 'compare':
        return {
            'message_kind': 'compare',
            'narrative_text': narrative_text,
            'symbols': [e.symbol for e in (judgment.compare_entries or [])],
            'freshness_meta': freshness_meta,
        }
    if kind == 'exit':
        return {
            'message_kind': 'exit',
            'narrative_text': narrative_text,
            'symbol': (judgment.subject_entry.symbol if judgment.subject_entry else None),
            'freshness_meta': freshness_meta,
        }
    if kind == 'run_change':
        return {
            'message_kind': 'run_change',
            'narrative_text': narrative_text,
            'freshness_meta': freshness_meta,
        }
    if kind == 'chat':
        return {
            'message_kind': 'chat',
            'narrative_text': narrative_text,
            'followup_suggestions': [
                '今天给我 3 只',
                '为什么今天空仓',
                '对 600519 卖出判断',
            ],
            'freshness_meta': freshness_meta,
        }
    if kind == 'no_trade':
        return {
            'message_kind': 'no_trade',
            'narrative_text': narrative_text,
            'reason': judgment.summary,
            'freshness_meta': freshness_meta,
        }
    return {
        'message_kind': 'followup',
        'narrative_text': narrative_text,
        'freshness_meta': freshness_meta,
    }


def _dialogue_context(turns: List[TranscriptEvent] | None) -> List[Dict[str, Any]]:
    if not turns:
        return []
    out: List[Dict[str, Any]] = []
    for turn in turns[-6:]:
        meta = turn.meta or {}
        message = meta.get("message") if isinstance(meta, dict) else None
        item: Dict[str, Any] = {
            "role": turn.role,
            "content": turn.content,
        }
        if isinstance(message, dict):
            item["message_kind"] = message.get("message_kind")
            item["symbols"] = message.get("symbols") or meta.get("symbols") or []
        out.append(item)
    return out


def build_reply(
    session_id: str,
    frame: TurnFrame,
    evidence: EvidencePack,
    judgment: Judgment,
    *,
    recent_turns: List[TranscriptEvent] | None = None,
) -> ReplyBundle:
    text = render_reply({
        'frame': frame.model_dump(),
        'judgment': judgment.model_dump(),
        'session_context': {
            'active_run_id': evidence.session.active_run_id,
            'previous_run_id': evidence.session.previous_run_id,
            'focus_subject': evidence.session.focus_subject,
            'compare_set': evidence.session.compare_set,
            'last_focus_symbol': evidence.session.last_focus_symbol,
        },
        'recent_dialogue': _dialogue_context(recent_turns),
        'evidence_summary': {
            'book_version': evidence.book.book_version,
            'board_symbols': [e.symbol for e in evidence.book.board[:6]],
            'active_run_id': evidence.active_run.run_id if evidence.active_run else None,
        },
    })
    symbols: List[str] = []
    if judgment.run is not None:
        symbols = [e.symbol for e in judgment.run.picks]
    elif judgment.subject_entry is not None:
        symbols = [judgment.subject_entry.symbol]
    elif judgment.compare_entries:
        symbols = [e.symbol for e in judgment.compare_entries]
    # Right panel top entries priority: judgment.run -> evidence.active_run -> book.board
    top3_entries: List[BoardEntry] = []
    if judgment.run is not None:
        top3_entries = judgment.run.picks  # respect true topk
    elif evidence.active_run is not None:
        top3_entries = evidence.active_run.picks[:3]
    else:
        top3_entries = evidence.book.board[:3]
    right_panel = {
        'trading_day': evidence.book.trading_day,
        'last_closed_5m': evidence.book.last_closed_5m,
        'tradeable': evidence.book.daybook.tradeable,
        'top3': [_canonical_pick(e) for e in top3_entries],
    }
    message = _build_canonical_message(evidence, judgment, text)
    return ReplyBundle(
        session_id=session_id,
        text=text,
        kind=judgment.kind,
        run_id=judgment.run.run_id if judgment.run else None,
        symbols=symbols,
        right_panel=right_panel,
        ui_items=[],
        message=message,
        evidence_refs=judgment.evidence_refs,
        planner_trace={'frame': frame.model_dump()},
    )
