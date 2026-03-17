from __future__ import annotations

"""
Validator for PickArtifactV2.

Checks:
- Required top-level fields exist
- Numeric fields are finite
- entry_zone valid and ordered
- take_profit non-empty and ordered when present
- reward_risk >= 0, signal_age_days >= 0
- Scores in [0,1]
- execution_state / liquidity_grade / volatility_grade in enums
- actionable=true cannot be observe_only/below_support/breakdown_risk/invalidated_now
- tradeable=false should not carry actionable=true items

Phase 2.6 semantics:
- invalidation: list of rule descriptors (conditions), not immediate status.
- invalidated_now: boolean current status; only this can block actionable.
  When absent, it is treated as False by default.
"""

from typing import Any, Dict, List, Tuple

from .contracts import EXECUTION_STATES, LIQUIDITY_GRADES, VOLATILITY_GRADES


def _is_finite_number(v: Any) -> bool:
    try:
        x = float(v)
        if x != x:
            return False
        if x in (float("inf"), float("-inf")):
            return False
        return True
    except Exception:
        return False


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def validate_pick_artifact_v2(obj: Dict[str, Any]) -> Tuple[bool, List[str], Dict[str, Any]]:
    errors: List[str] = []

    # Required top-level
    for k in ["run_id", "as_of", "degraded", "tradeable", "symbols", "themes", "items"]:
        if k not in obj:
            errors.append(f"missing_top_field:{k}")

    items = obj.get("items") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        errors.append("items_not_list")
        items = []

    # Validate items
    fixed_items: List[Dict[str, Any]] = []
    for i, it in enumerate(items or []):
        if not isinstance(it, dict):
            errors.append(f"item_{i}_not_dict")
            continue
        # required item fields
        for k in ["pick_id", "symbol"]:
            if k not in it:
                errors.append(f"item_{i}_missing:{k}")
        # entry_zone ordering if present
        ez = it.get("entry_zone")
        if ez is not None:
            ok = False
            try:
                if isinstance(ez, (list, tuple)) and len(ez) >= 2 and _is_finite_number(ez[0]) and _is_finite_number(ez[1]):
                    a = float(ez[0]); b = float(ez[1])
                    if a <= b:
                        ok = True
                        it["entry_zone"] = [a, b]
                else:
                    errors.append(f"item_{i}_bad_entry_zone")
            except Exception:
                errors.append(f"item_{i}_bad_entry_zone")
            if not ok:
                errors.append(f"item_{i}_entry_zone_invalid")
        # stop numeric optional
        if it.get("stop") is not None and not _is_finite_number(it.get("stop")):
            errors.append(f"item_{i}_bad_stop")
        # take_profit ordered non-empty if provided
        tp = it.get("take_profit")
        if tp is not None:
            if not isinstance(tp, list) or not tp:
                errors.append(f"item_{i}_take_profit_empty")
            else:
                try:
                    vals = [float(x) for x in tp]
                    if any((v != v or v in (float('inf'), float('-inf'))) for v in vals):
                        errors.append(f"item_{i}_take_profit_nonfinite")
                    it["take_profit"] = sorted(vals)
                except Exception:
                    errors.append(f"item_{i}_take_profit_nonnumeric")
        # reward_risk >= 0
        if it.get("reward_risk") is not None:
            try:
                rr = float(it.get("reward_risk"))
                if rr < 0:
                    errors.append(f"item_{i}_reward_risk_negative")
            except Exception:
                errors.append(f"item_{i}_reward_risk_nonnum")
        # signal_age_days >= 0
        if it.get("signal_age_days") is not None:
            try:
                if int(it.get("signal_age_days")) < 0:
                    errors.append(f"item_{i}_signal_age_negative")
            except Exception:
                errors.append(f"item_{i}_signal_age_nonint")
        # scores in [0,1]
        for sk in ["alpha_score", "execution_score", "reliability_score", "final_score", "confidence"]:
            if it.get(sk) is not None:
                try:
                    it[sk] = _clamp01(float(it.get(sk)))
                except Exception:
                    errors.append(f"item_{i}_{sk}_nonnum")
        # enums
        st = it.get("execution_state")
        if st is not None and str(st) not in EXECUTION_STATES:
            errors.append(f"item_{i}_bad_execution_state")
        lg = it.get("liquidity_grade")
        if lg is not None and str(lg) not in LIQUIDITY_GRADES:
            errors.append(f"item_{i}_bad_liquidity_grade")
        vg = it.get("volatility_grade")
        if vg is not None and str(vg) not in VOLATILITY_GRADES:
            errors.append(f"item_{i}_bad_volatility_grade")
        # actionable coherence
        if it.get("actionable") is True:
            if str(it.get("execution_state")) in {"observe_only", "breakdown_risk", "below_support"}:
                errors.append(f"item_{i}_actionable_state_conflict")
            # Phase 2.6: only invalidated_now blocks actionable; rule list alone does not
            inv_now = bool(it.get("invalidated_now") is True)
            if inv_now:
                errors.append(f"item_{i}_actionable_invalidated_now_conflict")
        fixed_items.append(it)

    # tradeable false with actionable items -> conflict
    try:
        if obj.get("tradeable") is False:
            for i, it in enumerate(fixed_items):
                if bool(it.get("actionable") is True):
                    errors.append(f"top_tradeable_false_but_item_{i}_actionable_true")
    except Exception:
        pass

    fixed = dict(obj)
    fixed["items"] = fixed_items
    ok = len(errors) == 0
    return ok, errors, fixed
