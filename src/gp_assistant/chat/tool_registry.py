from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import session_store as store
from ..kernel.facade import (
    get_gated_artifact_v2 as _get_gated_artifact_v2,
    compare_symbols as _compare_symbols,
    get_pick_detail as _get_pick_detail,
)
from ..recommend.runner import run as _recommend_run
from ..recommend.artifact_store import build_v2_dict_from_v1, persist_artifact_v2


class ToolError(RuntimeError):
    pass


class ToolRegistry:
    """High-level semantic tools used by the finance agent.

    All tools are deterministic and do not depend on user phrasing.
    """

    def __init__(self) -> None:
        pass

    # 1. get_session_context
    def get_session_context(self, session_id: str) -> Dict[str, Any]:
        sid = store.ensure_session(session_id)
        st = store.get_state(sid)
        # Last bundle summary can be attached by agent (best-effort via right_panel)
        last_bundle_summary = None
        try:
            rp = st.get("last_right_panel")
            if isinstance(rp, dict):
                last_bundle_summary = {
                    "active_run_id": rp.get("active_run_id"),
                    "tradeable": rp.get("tradeable"),
                    "run_gating": rp.get("run_gating"),
                    "active_symbols": rp.get("active_symbols"),
                }
        except Exception:
            pass
        return {
            "active_run_id": st.get("active_run_id"),
            "previous_run_id": st.get("previous_run_id"),
            "focus_symbol": st.get("focused_symbol") or st.get("current_focus_symbol"),
            "active_symbols": st.get("active_symbols") or [],
            "last_topk": None,
            "last_bundle_id": None,
            "market_session": None,
            "last_bundle_summary": last_bundle_summary,
        }

    # 2. ensure_recommendation
    def ensure_recommendation(self, session_id: str, *, topk: Optional[int] = None, refresh: bool = False) -> Dict[str, Any]:
        sid = store.ensure_session(session_id)
        st = store.get_state(sid)
        run_id = None if refresh else (st.get("active_run_id") or None)

        # Try gated artifact first
        try:
            art = _get_gated_artifact_v2(run_id=run_id)
        except Exception:
            art = {}

        # If missing or refresh requested, compute a fresh run via runner and persist to v2
        if refresh or not isinstance(art, dict) or not art.get("items"):
            v1 = _recommend_run(mode="default", date=None, topk=topk or 3, universe="auto", symbols=None, risk_profile="normal")
            v2 = build_v2_dict_from_v1(v1)
            rid = str(v2.get("run_id") or v2.get("as_of") or "")
            if rid:
                try:
                    persist_artifact_v2(rid, v2)
                except Exception:
                    pass
            art = _get_gated_artifact_v2(run_id=rid or None)

        items = art.get("items") or []
        symbols = [str((it or {}).get("symbol") or "") for it in items if isinstance(it, dict) and (it or {}).get("symbol")]

        # Update session context
        store.update_state(sid, {
            "active_run_id": art.get("run_id") or art.get("as_of"),
            "active_symbols": list(symbols),
        })

        return {
            "active_run_id": art.get("run_id"),
            "tradeable": bool(art.get("tradeable")),
            "run_gating": art.get("run_gating"),
            "items": items,
            "as_of": art.get("as_of"),
            "reused_run": (run_id is not None and run_id == art.get("run_id")),
            "stale": False,
            "refresh_reason": ("force_refresh" if refresh else None),
        }

    # 3. resolve_reference
    def resolve_reference(self, session_id: str, raw_reference: str) -> Dict[str, Any]:
        st = store.get_state(session_id)
        s = (raw_reference or "").strip()
        active = list(st.get("active_symbols") or [])
        focus = st.get("focused_symbol") or st.get("current_focus_symbol")

        # Explicit symbol present?
        import re
        m = re.search(r"\b(\d{6})\b", s)
        if m:
            sym = m.group(1)
            return {"resolution_type": "symbol", "symbol": sym, "based_on": ("active_set" if sym in active else "explicit")}

        # Ordinal: 第一只/第二只/第三只 ... or ‘第一/第二/第三’
        ordinal_map = {"第一": 1, "第二": 2, "第三": 3, "第四": 4, "第五": 5}
        for k, idx in ordinal_map.items():
            if k in s:
                i = idx - 1
                if 0 <= i < len(active):
                    return {"resolution_type": "ordinal", "ordinal": idx, "symbol": active[i], "based_on": "ordinal"}
                return {"resolution_type": "ordinal", "ordinal": idx, "based_on": "ordinal"}

        # ‘这只/这票/当前这票’
        if any(x in s for x in ["这只", "这票", "当前这票", "这一个", "这个"]):
            if focus:
                return {"resolution_type": "symbol", "symbol": str(focus), "based_on": "focus"}
            if active:
                return {"resolution_type": "symbol", "symbol": active[0], "based_on": "active_set"}

        # set/these
        if any(x in s for x in ["这三支", "这几个", "这几只"]):
            if active:
                return {"resolution_type": "selection_set", "symbols": active[:3], "based_on": "active_set"}

        return {"resolution_type": "none", "based_on": None}

    # 4. explain_selection_set
    def explain_selection_set(self, session_id: str) -> Dict[str, Any]:
        st = store.get_state(session_id)
        art = _get_gated_artifact_v2(run_id=st.get("active_run_id"))
        items = art.get("items") or []
        top = [str((it or {}).get("symbol") or "") for it in items[:3] if isinstance(it, dict)]
        per_symbol = {}
        for it in items:
            try:
                per_symbol[str(it.get("symbol"))] = it.get("thesis") or it.get("strategy_label") or it.get("strategy")
            except Exception:
                continue
        out = {
            "top_symbols": top,
            "per_symbol_rationale": per_symbol,
            "ranking_rationale": "derived_from_scores",
        }
        if not bool(art.get("tradeable")):
            out["note"] = "NO-TRADE: 候选观察/排序解释，不是可执行推荐"
        return out

    # 5. get_pick_detail
    def get_pick_detail(self, session_id: str, symbol: str) -> Dict[str, Any]:
        st = store.get_state(session_id)
        run_id = st.get("active_run_id")
        detail = _get_pick_detail(run_id, symbol)
        item = detail.get("item") or {}
        return {
            "symbol": symbol,
            "thesis": item.get("thesis"),
            "entry_zone": item.get("entry_zone"),
            "stop": item.get("stop"),
            "take_profit": item.get("take_profit"),
            "reward_risk": item.get("reward_risk"),
            "execution_state": item.get("execution_state"),
            "gating_decision": item.get("gating_decision"),
            "actionable": item.get("actionable"),
            "invalidation": item.get("invalidation"),
            "risk_flags": item.get("risk_flags"),
            "supports_new_entry": bool(item.get("actionable")),
        }

    # 6. compare_symbols
    def compare_symbols(self, session_id: str, symbols: List[str]) -> Dict[str, Any]:
        st = store.get_state(session_id)
        active = set(st.get("active_symbols") or [])
        syms = [s for s in (symbols or []) if s in active]
        return _compare_symbols(st.get("active_run_id"), syms)

    # 7. get_exit_decision
    def get_exit_decision(self, session_id: str, symbol: str) -> Dict[str, Any]:
        # Deterministic, derived from current item state
        d = self.get_pick_detail(session_id, symbol)
        action = "hold"
        pri = []
        if not bool(d.get("actionable")):
            action = "hold"
            pri.append("not_actionable")
        else:
            action = "hold_or_trail"
            pri.append("trend_follow_with_trailing")
        return {
            "action": action,
            "summary_reason": ". ".join(pri),
            "primary_reasons": pri,
            "trigger_conditions": ["break_below_stop", "invalidate_thesis"],
            "risk_notes": d.get("risk_flags") or [],
            "supports_new_entry": bool(d.get("actionable")),
        }

    # 8. get_run_change
    def get_run_change(self, session_id: str) -> Dict[str, Any]:
        st = store.get_state(session_id)
        curr = list(st.get("active_symbols") or [])
        prev = list(st.get("previous_active_symbols") or [])
        added = [s for s in curr if s and s not in prev]
        removed = [s for s in prev if s and s not in curr]
        rank_changes: List[Dict[str, Any]] = []  # placeholder for later stable rank diffs
        tradeable_change = None
        run_gating_change = None
        summary_reason = "selection_updated" if (added or removed) else "no_change"
        return {
            "current_run_id": st.get("active_run_id"),
            "previous_run_id": st.get("previous_run_id"),
            "added_symbols": added,
            "removed_symbols": removed,
            "rank_changes": rank_changes,
            "tradeable_change": tradeable_change,
            "run_gating_change": run_gating_change,
            "summary_reason": summary_reason,
        }

    # 9. set_focus_symbol
    def set_focus_symbol(self, session_id: str, symbol: str) -> Dict[str, Any]:
        return store.set_focus(session_id, symbol, reason="agent_tool")


def build_registry() -> ToolRegistry:
    return ToolRegistry()

