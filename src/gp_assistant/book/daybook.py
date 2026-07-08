from __future__ import annotations

from typing import Any, Dict, List

from ..contracts.objects import AdvicePick, DayBook
from ..evidence.market_service import build_day_selection
from ..runtime.utils import now_iso


def _pick_style(item: Dict[str, Any]) -> str:
    risk_flags = [str(x) for x in (item.get('risk_flags') or [])]
    ranking_score = float((item.get('ranking') or {}).get('ranking_score') or item.get('ranking_score') or 0.0)
    if any('uncertainty' in x.lower() or 'drawdown' in x.lower() for x in risk_flags):
        return 'aggressive'
    if ranking_score >= 0.0008:
        return 'balanced'
    return 'stable'


def _map_pick(rank: int, item: Dict[str, Any]) -> AdvicePick:
    trade_plan = item.get('trade_plan') or {}
    diag = trade_plan.get('diagnostics') or {}
    symbol = str(item.get('symbol') or item.get('code') or '').strip()
    probability = dict(item.get('probability') or {})
    risk = dict(item.get('risk') or {})
    ranking = dict(item.get('ranking') or {})
    signal = dict(item.get('signal') or {})
    evidence = dict(probability.get('evidence') or {})
    # Prefer user-visible fields; do not leak debug explain
    user_thesis = item.get('user_thesis')
    why_selected_text = item.get('why_selected_text')
    thesis_fallback = item.get('thesis')
    return AdvicePick(
        symbol=symbol,
        name=item.get('name'),
        rank=rank,
        strategy_id=str(item.get('signal_type') or signal.get('signal_type') or ''),
        industry=str(item.get('industry') or item.get('theme') or '').strip() or None,
        thesis=str(user_thesis or thesis_fallback or ''),
        entry_plan=trade_plan.get('entry') or item.get('entry_plan') or {},
        stop_plan=trade_plan.get('stop') or item.get('stop_plan') or {},
        take_profit_plan=trade_plan.get('take_profit') or item.get('take_profit_plan') or {},
        scores={
            'final': float(ranking.get('ranking_score') or item.get('ranking_score') or 0.0),
            'ranking': float(ranking.get('ranking_score') or 0.0),
            'probability': float(probability.get('up_probability_3d') or 0.0),
            'expected_return': float(probability.get('expected_return_3d') or 0.0),
            'execution_quality': float(risk.get('execution_quality') or 0.0),
            'confidence': float(probability.get('confidence') or 0.0),
            'reward_risk': float(diag.get('reward_risk') or 0.0),
        },
        risk_flags=[str(x) for x in (item.get('risk_flags') or [])],
        why_selected=str(why_selected_text or ''),
        why_not_others=[str(x) for x in (item.get('why_not') or [])],
        evidence_refs=[symbol],
        style_label=_pick_style(item),
        meta={
            'execution_state': str(diag.get('execution_state') or ''),
            'actionable': bool(diag.get('actionable') is True),
            'reason_codes': [str(x) for x in (item.get('reason_codes') or [])],
            'daily_last_date': item.get('last_date'),
            'daily_freshness_state': item.get('daily_freshness_state'),
            'signal_type': item.get('signal_type') or signal.get('signal_type'),
            'sample_size': evidence.get('sample_size'),
            'effective_sample_size': evidence.get('effective_sample_size'),
            'mean_similarity': evidence.get('mean_similarity'),
            'uncertainty': probability.get('uncertainty'),
            'decision_context_snapshot_id': item.get('decision_context_snapshot_id'),
            'rejected_reason': item.get('rejected_reason'),
        },
        signal=signal,
        probability=probability,
        risk=risk,
        ranking=ranking,
        historical_cases=list(item.get('historical_cases') or []),
        decision_context_snapshot_id=item.get('decision_context_snapshot_id'),
    )


def build_daybook(trading_day: str, *, topk: int = 10, reserve_count: int = 2, risk_profile: str = 'normal') -> DayBook:
    raw = build_day_selection(trading_day, topk=topk, risk_profile=risk_profile)
    freshness = raw.get('daily_freshness') or {}
    picks = [_map_pick(i + 1, item) for i, item in enumerate(raw.get('picks') or []) if str(item.get('symbol') or item.get('code') or '').strip()]
    reserve: list[str] = []
    reserve_picks: list[AdvicePick] = []
    pick_symbols = {p.symbol for p in picks}
    for cand in raw.get('candidate_pool') or []:
        sym = str(cand.get('symbol') or cand.get('code') or '').strip()
        if sym and sym not in reserve and sym not in pick_symbols:
            reserve.append(sym)
            reserve_picks.append(_map_pick(len(picks) + len(reserve_picks) + 1, cand))
        if len(reserve) >= reserve_count:
            break
    return DayBook(
        trading_day=trading_day,
        generated_at=now_iso(),
        regime=raw.get('env') or {},
        tradeable=bool(raw.get('tradeable', bool(picks))),
        reason=raw.get('message') or raw.get('reason'),
        themes=[],
        picks=picks,
        reserve_picks=reserve_picks,
        reserve_symbols=reserve,
        source_meta={
            'raw_keys': sorted(list(raw.keys())),
            'topk': topk,
            'reserve_count': reserve_count,
            'risk_profile': risk_profile,
            'daily_freshness': freshness,
            'decision_context_snapshot_id': raw.get('decision_context_snapshot_id'),
            'decision': raw.get('decision'),
        },
    )
