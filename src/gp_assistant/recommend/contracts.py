from __future__ import annotations

"""
PickArtifactV2 contract and helpers.

This module defines the canonical V2 artifact shape and provides
utilities to build V2 from the current engine payload (v1-style).

Phase 2 goals:
- Unify recommendation output as PickArtifactV2
- Keep deterministic, LLM-free numeric fields
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# --- Controlled enums (Phase 2) ---
EXECUTION_STATES = {
    "actionable",
    "waiting_pullback",
    "observe_only",
    "below_support",
    "breakdown_risk",
}

LIQUIDITY_GRADES = {"A", "B", "C"}
VOLATILITY_GRADES = {"low", "medium", "high"}


@dataclass
class EvidencePlaceholder:
    available: bool = False
    status: str = "pending_phase3"
    # Phase 3 evidence blocks (optional; keep placeholders)
    event_stats: Dict[str, Any] = field(default_factory=dict)
    walk_forward: Dict[str, Any] = field(default_factory=dict)
    paper_trade: Dict[str, Any] = field(default_factory=dict)
    strategy_health: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PickItemV2:
    pick_id: str
    symbol: str
    name: Optional[str] = None
    strategy: Optional[str] = None
    strategy_label: Optional[str] = None
    thesis: Optional[str] = None
    price_ref: Optional[float] = None
    entry_zone: Optional[Tuple[float, float]] = None
    stop: Optional[float] = None
    take_profit: List[float] = field(default_factory=list)
    reward_risk: Optional[float] = None
    execution_state: Optional[str] = None
    actionable: Optional[bool] = None
    # Scores (Phase 2)
    alpha_score: Optional[float] = None
    execution_score: Optional[float] = None
    reliability_score: Optional[float] = None
    final_score: Optional[float] = None
    confidence: Optional[float] = None
    signal_age_days: Optional[int] = None
    liquidity_grade: Optional[str] = None
    volatility_grade: Optional[str] = None
    risk_flags: List[str] = field(default_factory=list)
    invalidation: List[str] = field(default_factory=list)
    # Phase 2.6: separate current invalidated status from rule list
    invalidated_now: bool = False
    notes: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=lambda: EvidencePlaceholder().__dict__)
    # Phase 2.6: internal score basis (not for frontend reliance)
    _score_inputs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PickArtifactV2:
    run_id: str
    as_of: str
    as_of_ts: Optional[str]
    trading_date: Optional[str]
    data_cutoff: Optional[str]
    snapshot_id: Optional[str]
    market_regime: Optional[str]
    degraded: bool
    tradeable: bool
    reason: Optional[str]
    risk_profile: Optional[str]
    universe_name: Optional[str]
    symbols: List[str]
    themes: List[str]
    items: List[PickItemV2]


def _safe_float(v: Any) -> Optional[float]:
    try:
        x = float(v)
        if x != x or x in (float("inf"), float("-inf")):
            return None
        return x
    except Exception:
        return None


def _safe_int(v: Any) -> Optional[int]:
    try:
        i = int(v)
        if i < 0:
            return None
        return i
    except Exception:
        try:
            f = float(v)
            if f != f or f in (float("inf"), float("-inf")):
                return None
            if f < 0:
                return None
            return int(f)
        except Exception:
            return None


def _derive_vol_grade(atr_pct: Optional[float]) -> Optional[str]:
    if atr_pct is None:
        return None
    a = float(atr_pct)
    if a < 0.02:
        return "low"
    if a < 0.06:
        return "medium"
    return "high"


def build_v2_from_v1(payload: Dict[str, Any], *, risk_profile: Optional[str] = None, universe: Optional[str] = None) -> PickArtifactV2:
    """
    Convert current v1 engine payload to PickArtifactV2.

    This is the canonical bridge used during Phase 2 while the engine
    still persists v1 artifacts to disk. All fields are filled via
    deterministic mappings only.
    """
    as_of = str(payload.get("as_of") or "")
    run_id = as_of or str(payload.get("run_id") or "")
    themes_in = payload.get("themes") or []
    theme_names: List[str] = []
    if isinstance(themes_in, list):
        for t in themes_in:
            try:
                nm = str((t or {}).get("name") or "").strip()
                if nm:
                    theme_names.append(nm)
            except Exception:
                continue

    # Snapshot id best-effort from data_status.snapshot.as_of_ts
    snapshot_id = None
    as_of_ts = None
    try:
        ds = payload.get("data_status", {}) or {}
        snapshot = (ds.get("snapshot", {}) or {})
        snapshot_id = snapshot.get("as_of_ts")
        as_of_ts = snapshot_id
    except Exception:
        snapshot_id = None
        as_of_ts = None

    # market_regime from env.grade if available
    regime = None
    try:
        regime = str((payload.get("env") or {}).get("grade") or "").strip() or None
    except Exception:
        regime = None

    # degraded flag from debug
    degraded = False
    try:
        degraded = bool((payload.get("debug") or {}).get("degraded") is True)
    except Exception:
        degraded = False

    tradeable = bool(payload.get("tradeable") is True)
    reason = None
    try:
        if tradeable is False:
            reason = str(payload.get("message") or "") or None
    except Exception:
        pass

    # Universe name best-effort (dynamic_pool|symbols|universe:file)
    universe_name = universe
    try:
        # prefer candidate_pool base reasons if present
        pool = payload.get("candidate_pool") or []
        if isinstance(pool, list) and pool:
            br = str((pool[0] or {}).get("source_reason") or "").strip()
            if br:
                universe_name = br
    except Exception:
        pass

    # Build items from picks
    picks_in = payload.get("picks") or []
    items: List[PickItemV2] = []
    symbols: List[str] = []
    # map for liquidity by symbol from pool when available
    liq_by_sym: Dict[str, str] = {}
    atr_by_sym: Dict[str, float] = {}
    flags_by_sym: Dict[str, List[str]] = {}
    try:
        pool = payload.get("candidate_pool") or []
        if isinstance(pool, list):
            for c in pool:
                try:
                    s = str((c or {}).get("symbol") or "").strip()
                    if not s:
                        continue
                    liq = (((c or {}).get("liquidity") or {}).get("grade"))
                    if isinstance(liq, str):
                        liq_by_sym[s] = liq
                    atr = (((c or {}).get("indicators") or {}).get("atr_pct"))
                    atr_by_sym[s] = float(atr) if atr is not None else atr_by_sym.get(s, 0.0)
                    fl = (((c or {}).get("flags") or {}).get("reasons") or [])
                    if isinstance(fl, list):
                        flags_by_sym[s] = [str(x) for x in fl if isinstance(x, str)]
                except Exception:
                    continue
    except Exception:
        pass

    for p in (picks_in if isinstance(picks_in, list) else []):
        try:
            sym = str((p or {}).get("symbol") or "").strip()
            if not sym:
                continue
            symbols.append(sym)
            tp = (p.get("trade_plan") or {}) if isinstance(p, dict) else {}
            diag = (tp.get("diagnostics") or {}) if isinstance(tp, dict) else {}
            champ = (p.get("champion") or {}) if isinstance(p, dict) else {}
            name = p.get("name") if isinstance(p.get("name"), str) else None
            # price_ref from last_close if available
            price_ref = _safe_float(p.get("last_close"))
            # entry zone from tp.entry; if scalar -> make a tight band around it
            entry_zone: Optional[Tuple[float, float]] = None
            try:
                ent = tp.get("entry")
                if isinstance(ent, list) and len(ent) >= 2:
                    a = _safe_float(ent[0]); b = _safe_float(ent[1])
                    if a is not None and b is not None:
                        lo, hi = (a, b) if a <= b else (b, a)
                        entry_zone = (lo, hi)
                elif isinstance(ent, (int, float)):
                    v = _safe_float(ent)
                    if v is not None:
                        entry_zone = (v * 0.995, v * 1.005)
            except Exception:
                entry_zone = None
            # stop from S1 (close-below support)
            stop = None
            try:
                bands = tp.get("bands") or {}
                stop = _safe_float(bands.get("S1"))
            except Exception:
                stop = None
            # take_profit from tp.take
            take_profit: List[float] = []
            try:
                tk = tp.get("take")
                if isinstance(tk, list):
                    for v in tk:
                        vv = _safe_float(v)
                        if vv is not None:
                            take_profit.append(vv)
                elif isinstance(tk, (int, float)):
                    vv = _safe_float(tk)
                    if vv is not None:
                        take_profit.append(vv)
            except Exception:
                take_profit = []
            # rr/actionable/state
            rr = _safe_float(diag.get("reward_risk"))
            actionable = bool(diag.get("actionable") is True)
            state = str(diag.get("execution_state") or "") or None
            # signal age from setup_age (bars proxy)
            age = _safe_int(diag.get("setup_age"))
            # liquidity grade best-effort
            liq = liq_by_sym.get(sym)
            # volatility from ATR
            vol = _derive_vol_grade(atr_by_sym.get(sym)) if sym in atr_by_sym else None
            # risk/invalid
            invalid = []
            try:
                invalid = [str(x) for x in (tp.get("invalidation") or []) if isinstance(x, str)]
            except Exception:
                invalid = []
            risk_flags = flags_by_sym.get(sym, [])
            # strategy
            strategy = str(champ.get("strategy")) if champ.get("strategy") is not None else None
            # simple template thesis
            thesis = None
            try:
                theme = str(p.get("theme") or "").strip()
                if theme and strategy:
                    thesis = f"{theme} · {strategy} setup"
                elif strategy:
                    thesis = f"{strategy} setup"
                elif theme:
                    thesis = f"{theme}"
            except Exception:
                thesis = None
            # build item
            # build internal score basis
            basis: Dict[str, Any] = {}
            try:
                if champ.get("score") is not None:
                    basis["champion_score_raw"] = _safe_float(champ.get("score")) or 0.0
            except Exception:
                pass
            try:
                if rr is not None:
                    basis["reward_risk_raw"] = rr
            except Exception:
                pass
            try:
                if age is not None:
                    basis["setup_age_raw"] = age
            except Exception:
                pass
            try:
                basis["degraded_input"] = bool(degraded)
            except Exception:
                pass
            try:
                if liq is not None:
                    basis["liquidity_raw"] = liq
            except Exception:
                pass
            # Optional entry gap percent when entry_zone & price_ref present
            try:
                if price_ref is not None and entry_zone is not None:
                    lo, hi = entry_zone
                    mid = (float(lo) + float(hi)) / 2.0
                    if mid:
                        basis["entry_gap_pct"] = (float(price_ref) - mid) / mid
            except Exception:
                pass

            item = PickItemV2(
                pick_id=f"{run_id}:{sym}",
                symbol=sym,
                name=name,
                strategy=strategy,
                strategy_label=strategy,
                thesis=thesis,
                price_ref=price_ref,
                entry_zone=entry_zone,
                stop=stop,
                take_profit=sorted(take_profit) if take_profit else [],
                reward_risk=rr,
                execution_state=state,
                actionable=actionable,
                # Phase 2.6: default not invalidated unless we can prove otherwise
                invalidated_now=False,
                signal_age_days=age,
                liquidity_grade=liq,
                volatility_grade=vol,
                risk_flags=risk_flags,
                invalidation=invalid,
                _score_inputs=basis,
            )
            items.append(item)
        except Exception:
            continue

    # Determine trading_date and data_cutoff from payload only (no reliance on current clock)
    def _safe_date_from_any(s: Optional[str]) -> Optional[str]:
        if not s:
            return None
        t = str(s).strip().replace("/", "-")
        if len(t) >= 8 and t[:8].isdigit():
            return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
        try:
            return str(s).split("T", 1)[0]
        except Exception:
            return None

    trading_date = _safe_date_from_any(as_of) or _safe_date_from_any(as_of_ts)

    # cutoff inference: prefer explicit payload field; else infer conservatively from as_of_ts
    data_cutoff: Optional[str] = None
    try:
        # v1 payload may carry an explicit cutoff
        explicit = str((payload.get("data_cutoff") or payload.get("cutoff") or "")).upper().strip()
        if explicit in {"INTRADAY", "EOD"}:
            data_cutoff = explicit
    except Exception:
        data_cutoff = None
    if not data_cutoff:
        # Use conservative inference from snapshot time
        hhmm = None
        try:
            s = str(as_of_ts or "").strip()
            if "T" in s:
                _, t = s.split("T", 1)
            elif " " in s:
                _, t = s.split(" ", 1)
            else:
                t = ""
            if t:
                parts = t.split(":")
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    hhmm = (int(parts[0]), int(parts[1]))
        except Exception:
            hhmm = None
        if trading_date and hhmm is not None:
            data_cutoff = "INTRADAY" if hhmm < (15, 5) else "EOD"
        else:
            # Historical/unknown snapshot time -> EOD by default
            data_cutoff = "EOD"

    return PickArtifactV2(
        run_id=run_id,
        as_of=as_of,
        as_of_ts=(str(as_of_ts) if as_of_ts else None),
        trading_date=trading_date,
        data_cutoff=str(data_cutoff or "INTRADAY"),
        snapshot_id=(str(snapshot_id) if snapshot_id else None),
        market_regime=regime,
        degraded=bool(degraded),
        tradeable=bool(tradeable),
        reason=reason,
        risk_profile=risk_profile,
        universe_name=universe or universe_name,
        symbols=symbols,
        themes=theme_names,
        items=items,
    )
