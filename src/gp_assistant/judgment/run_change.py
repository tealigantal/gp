from __future__ import annotations

from typing import Iterable

from ..contracts.objects import Judgment, AdviceRun, BoardEntry


def _syms(run: AdviceRun | None) -> set[str]:
    if not run or not run.picks:
        return set()
    return {str(e.symbol) for e in run.picks}


def _rank_map(run: AdviceRun | None) -> dict[str, int]:
    mp: dict[str, int] = {}
    if not run or not run.picks:
        return mp
    for e in run.picks:
        mp[str(e.symbol)] = int(e.rank)
    return mp


def judge_run_change(active: AdviceRun | None, previous: AdviceRun | None) -> Judgment:
    # Compute set differences and rank changes; tolerate missing runs by emitting empty diffs
    s_now = _syms(active)
    s_prev = _syms(previous)
    added = sorted(list(s_now - s_prev))
    removed = sorted(list(s_prev - s_now))
    common = sorted(list(s_now & s_prev))
    ranks_now = _rank_map(active)
    ranks_prev = _rank_map(previous)
    rank_changes = {
        sym: (ranks_prev.get(sym), ranks_now.get(sym)) for sym in common if ranks_prev.get(sym) != ranks_now.get(sym)
    }
    tradeable_change = None
    try:
        if active and previous:
            tradeable_change = (active.tradeable != previous.tradeable)
    except Exception:
        tradeable_change = None
    gating_change = None
    try:
        gating_change = {
            'reason_prev': (previous.reason if previous else None),
            'reason_now': (active.reason if active else None),
            'tradeable_prev': (previous.tradeable if previous else None),
            'tradeable_now': (active.tradeable if active else None),
        }
    except Exception:
        gating_change = None
    summary = (
        f"run_change: added={len(added)}, removed={len(removed)}, rank_changed={len(rank_changes)}, "
        f"tradeable_changed={bool(tradeable_change)}"
    )
    diff = {
        'added': added,
        'removed': removed,
        'rank_changes': rank_changes,
        'tradeable_change': tradeable_change,
        'gating_change': gating_change,
    }
    return Judgment(kind='run_change', summary=summary, compare_entries=[], diff=diff)
