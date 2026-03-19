from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Dict, Optional, Tuple

from . import session_store as store


@dataclass
class RunReuseDecision:
    action: str  # reuse | refresh | create
    run_id: Optional[str]
    reason: str
    stale: bool
    cache_level: str  # none | run_cache | stale
    refresh_reason: Optional[str]
    run_reuse_key: Optional[str] = None
    stale_reason: Optional[str] = None

    def to_right_panel(self) -> Dict[str, Any]:
        return {
            "reused_run": self.action == "reuse",
            "stale": self.stale,
            "cache_level": self.cache_level,
            "refresh_reason": self.refresh_reason,
            "stale_reason": self.stale_reason,
            "run_reuse_key": self.run_reuse_key,
        }


def _market_session(now: Optional[datetime] = None) -> str:
    dt = now or datetime.now()
    # rough Shanghai hours: pre<09:30, regular 09:30-15:00, post>15:00 local
    h, m = dt.hour, dt.minute
    if h < 9 or (h == 9 and m < 30):
        return "pre"
    if (h > 15) or (h == 15 and m >= 0):
        return "post"
    return "regular"


def _is_stale_and_reason(run_id: Optional[str]) -> Tuple[bool, Optional[str]]:
    if not run_id:
        return True, "no_active_run"
    s = str(run_id)
    try:
        if len(s) >= 8 and s[:8].isdigit():
            d = datetime.strptime(s[:8], "%Y%m%d").date()
            today = datetime.now().date()
            if d < today:
                return True, "previous_trading_day"
            # same day: session shift can mark as stale-ish
            sess = _market_session()
            # if run from pre and now regular/post: stale-ish
            # We do not know the original session; be conservative and mark fresh on same day
            return False, None
    except Exception:
        pass
    return False, None


def _build_key(session_state: Dict[str, Any], planner_out: Dict[str, Any]) -> str:
    run_id = session_state.get("active_run_id") or ""
    # derive trade_date from run_id
    trade_date = None
    if isinstance(run_id, str) and len(run_id) >= 8 and run_id[:8].isdigit():
        trade_date = run_id[:8]
    session = _market_session()
    risk_profile = (session_state.get("risk_profile") or "default")
    universe = (session_state.get("universe") or "auto")
    topk = planner_out.get("topk") or "default"
    intent = planner_out.get("intent") or "unknown"
    return f"date={trade_date}|sess={session}|risk={risk_profile}|uni={universe}|topk={topk}|intent={intent}"


def decide(session_id: str, planner_out: Dict[str, Any], user_message: str) -> RunReuseDecision:
    st = store.get_state(session_id)
    active_run_id = st.get("active_run_id")
    force_refresh = bool(planner_out.get("force_refresh"))
    intent = str(planner_out.get("intent") or "unknown")
    key = _build_key(st, planner_out)

    # Default policy
    if force_refresh:
        return RunReuseDecision(action="refresh", run_id=active_run_id, reason="planner_force_refresh", stale=False, cache_level="none", refresh_reason="user_requested", run_reuse_key=key)

    # Follow-up intents -> reuse
    followups = {
        "explain_no_trade",
        "analyze_symbol",
        "analyze_nth_pick",
        "compare_symbols",
        "exit_decision",
        "explain_ranking",
        "explain_run_change",
        "risk_points",
        "clarify_tradeability",
        "general_explain",
    }
    if intent in followups and active_run_id:
        stale, why = _is_stale_and_reason(active_run_id)
        return RunReuseDecision(action="reuse", run_id=active_run_id, reason="followup_reuse", stale=stale, cache_level=("stale" if stale else "run_cache"), refresh_reason=None, run_reuse_key=key, stale_reason=why)

    # recommend_topn: if have active and not stale, reuse; else create
    if intent == "recommend_topn":
        # Only reuse when same key except run_id freshness AND same requested topk
        req_topk = planner_out.get("topk")
        if active_run_id:
            stale, why = _is_stale_and_reason(active_run_id)
            if stale:
                return RunReuseDecision(action="refresh", run_id=active_run_id, reason="recommend_active_stale", stale=True, cache_level="stale", refresh_reason="stale", run_reuse_key=key, stale_reason=why)
            # Different topk should not reuse
            last_topk = st.get("last_topk")
            if last_topk is not None and req_topk is not None and int(last_topk) != int(req_topk):
                return RunReuseDecision(action="create", run_id=None, reason="topk_changed", stale=False, cache_level="none", refresh_reason=None, run_reuse_key=key)
            return RunReuseDecision(action="reuse", run_id=active_run_id, reason="recommend_reuse_recent", stale=False, cache_level="run_cache", refresh_reason=None, run_reuse_key=key)
        return RunReuseDecision(action="create", run_id=None, reason="no_active_run", stale=False, cache_level="none", refresh_reason=None, run_reuse_key=key)

    # If requires artifact but no active run -> create
    needs_run = intent in {"analyze_symbol", "analyze_nth_pick", "compare_symbols", "explain_ranking", "explain_no_trade", "exit_decision", "explain_run_change"}
    if needs_run and not active_run_id:
        return RunReuseDecision(action="create", run_id=None, reason="no_active_run_for_followup", stale=False, cache_level="none", refresh_reason=None, run_reuse_key=key)

    # default: reuse when possible
    if active_run_id:
        stale, why = _is_stale_and_reason(active_run_id)
        return RunReuseDecision(action="reuse", run_id=active_run_id, reason="default_reuse", stale=stale, cache_level=("stale" if stale else "run_cache"), refresh_reason=None, run_reuse_key=key, stale_reason=why)
    return RunReuseDecision(action="create", run_id=None, reason="no_active_run_default", stale=False, cache_level="none", refresh_reason=None, run_reuse_key=key)
