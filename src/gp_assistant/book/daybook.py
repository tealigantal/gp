from __future__ import annotations

from typing import Any, Dict, List

from ..contracts.objects import AdvicePick, DayBook
from ..evidence.market_service import build_day_selection
from ..runtime.utils import now_iso


def _pick_style(item: Dict[str, Any]) -> str:
    risk_flags = [str(x) for x in (item.get('risk_flags') or [])]
    final_score = float(item.get('final_score') or 0.0)
    if any('gap' in x.lower() or 'stretch' in x.lower() for x in risk_flags):
        return 'aggressive'
    if final_score >= 0.6:
        return 'balanced'
    return 'stable'


def _map_pick(rank: int, item: Dict[str, Any]) -> AdvicePick:
    trade_plan = item.get('trade_plan') or {}
    diag = trade_plan.get('diagnostics') or {}
    champion = item.get('champion') or {}
    symbol = str(item.get('symbol') or item.get('code') or '').strip()
    # Prefer user-visible fields; do not leak debug explain
    user_thesis = item.get('user_thesis')
    why_selected_text = item.get('why_selected_text')
    thesis_fallback = item.get('thesis')
    return AdvicePick(
        symbol=symbol,
        name=item.get('name'),
        rank=rank,
        strategy_id=str(champion.get('strategy') or item.get('strategy') or ''),
        industry=str(item.get('industry') or item.get('theme') or '').strip() or None,
        thesis=str(user_thesis or thesis_fallback or ''),
        entry_plan=trade_plan.get('entry') or item.get('entry_plan') or {},
        stop_plan=trade_plan.get('stop') or item.get('stop_plan') or {},
        take_profit_plan=trade_plan.get('take_profit') or item.get('take_profit_plan') or {},
        scores={
            'final': float(item.get('final_score') or 0.0),
            'candidate': float(item.get('candidate_score') or 0.0),
            'champion': float(champion.get('score') or 0.0),
            'reward_risk': float(diag.get('reward_risk') or 0.0),
        },
        risk_flags=[str(x) for x in (item.get('risk_flags') or [])],
        why_selected=str(why_selected_text or ''),
        why_not_others=[str(x) for x in (item.get('why_not') or [])],
        evidence_refs=[symbol],
        style_label=_pick_style(item),
        meta={
            'candidate_score': float(item.get('candidate_score') or 0.0),
            'theme_overlap_score': float(item.get('theme_overlap_score') or 0.0),
            'mainline_overlap_score': float(item.get('mainline_overlap_score') or 0.0),
            'reason_codes': [str(x) for x in (item.get('reason_codes') or [])],
            'daily_last_date': item.get('last_date'),
            'daily_freshness_state': item.get('daily_freshness_state'),
        },
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
    themes = [str(t.get('name')) for t in (raw.get('themes') or []) if isinstance(t, dict) and t.get('name')]
    return DayBook(
        trading_day=trading_day,
        generated_at=now_iso(),
        regime=raw.get('env') or {},
        tradeable=bool(raw.get('tradeable', bool(picks))),
        reason=raw.get('message') or raw.get('reason'),
        themes=themes,
        picks=picks,
        reserve_picks=reserve_picks,
        reserve_symbols=reserve,
        source_meta={
            'raw_keys': sorted(list(raw.keys())),
            'topk': topk,
            'reserve_count': reserve_count,
            'risk_profile': risk_profile,
            'daily_freshness': freshness,
        },
    )
