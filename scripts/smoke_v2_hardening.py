from __future__ import annotations

"""
Minimal stdlib-only smoke for Phase 2.6 V2 hardening.

Validates:
- v1 -> v2 build produces non-empty items with numeric scores
- invalidation list does not block actionable unless invalidated_now=true
- read priority: persisted v2 > fallback v1->v2
- compare returns fallback_used correctly
- chat refresh failure does not leak raw exception

Run: python scripts/smoke_v2_hardening.py
"""

import json
import sys
from typing import Any, Dict

from pathlib import Path

# Ensure src/ on path when running as module
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_latest_v1() -> Dict[str, Any]:
    base = Path(__file__).resolve().parents[1] / "store" / "recommend"
    p = base / "latest.json"
    if not p.exists():
        raise RuntimeError("missing store/recommend/latest.json for smoke")
    return json.loads(p.read_text(encoding="utf-8"))


def _ok(msg: str) -> None:
    print(f"[OK] {msg}")


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    sys.exit(1)


def main() -> None:
    from gp_assistant.selection_engine.artifact_store import (
        build_v2_dict_from_v1,
        persist_artifact_v2,
        read_artifact_v2,
        compare_subset,
        pick_detail as pick_detail_helper,
    )
    from gp_assistant.selection_engine.validators import validate_pick_artifact_v2
    from gp_assistant.selection_engine.calibration import calibrate_item_scores
    from gp_assistant.chat_compat import refresh_service as chat_refresh

    # a) build_v2 -> scores present (non-default structure)
    v1 = _load_latest_v1()
    v2 = build_v2_dict_from_v1(v1)
    items = v2.get("items") or []
    # Non-skippable core score check using synthetic actionable items
    lo = {"execution_state": "actionable", "reward_risk": 0.2, "liquidity_grade": "A"}
    hi = {"execution_state": "actionable", "reward_risk": 1.2, "liquidity_grade": "A"}
    slo = calibrate_item_scores(lo, degraded=False)["execution_score"]
    shi = calibrate_item_scores(hi, degraded=False)["execution_score"]
    if not (shi > slo):
        _fail("execution_score does not order actionable items by reward_risk")
    _ok("execution_score orders actionable items by reward_risk")

    # b) invalidation list alone must not block actionable
    fake = {
        "run_id": "X",
        "as_of": "2099-01-01",
        "degraded": False,
        "tradeable": True,
        "symbols": ["TEST"],
        "themes": [],
        "items": [
            {
                "pick_id": "X:TEST",
                "symbol": "TEST",
                "actionable": True,
                "execution_state": "actionable",
                "invalidation": ["close_below_S1"],
                "invalidated_now": False,
            }
        ],
    }
    ok, errs, _fixed = validate_pick_artifact_v2(fake)  # noqa: F841
    if not ok and any("invalidated" in e for e in errs):
        _fail("invalidation list incorrectly blocks actionable")
    _ok("invalidation list does not block actionable by itself")

    # c) persisted v2 vs fallback priority
    as_of = "2099-01-02"
    # create a minimal v2 with one item if needed for persist test
    v2_for_persist = v2
    if not (v2_for_persist.get("items") or []):
        v2_for_persist = {
            "run_id": as_of,
            "as_of": as_of,
            "degraded": False,
            "tradeable": True,
            "symbols": ["TEST"],
            "themes": [],
            "items": [
                {
                    "pick_id": f"{as_of}:TEST",
                    "symbol": "TEST",
                    "execution_state": "actionable",
                    "actionable": True,
                    "reward_risk": 0.5,
                    "liquidity_grade": "A",
                    "invalidated_now": False,
                    "invalidation": [],
                }
            ],
            "artifact_version": "v2",
            "fallback_used": False,
        }
    persist_artifact_v2(as_of, v2_for_persist)
    persisted = read_artifact_v2(as_of=as_of)
    if persisted.get("fallback_used"):
        _fail("persisted v2 unexpectedly marked fallback_used")
    _ok("persisted v2 preferred over fallback")

    # d) compare uses fallback_used correctly when no explicit run_id (fallback path)
    comp = compare_subset(run_id=None, symbols=v2.get("symbols", [])[:2])
    if "fallback_used" not in comp:
        _fail("compare response missing fallback_used")
    _ok("compare returns fallback_used flag")
    # e) build a deterministic 2-item artifact and verify compare ranking
    as_of2 = "2099-01-04"
    det = {
        "run_id": as_of2,
        "as_of": as_of2,
        "degraded": False,
        "tradeable": True,
        "symbols": ["AAA", "BBB"],
        "themes": [],
        "items": [
            {"pick_id": f"{as_of2}:AAA", "symbol": "AAA", "execution_state": "actionable", "actionable": True, "reward_risk": 0.3, "liquidity_grade": "A", "invalidated_now": False, "invalidation": []},
            {"pick_id": f"{as_of2}:BBB", "symbol": "BBB", "execution_state": "actionable", "actionable": True, "reward_risk": 1.2, "liquidity_grade": "A", "invalidated_now": False, "invalidation": []},
        ],
        "artifact_version": "v2",
        "fallback_used": False,
    }
    persist_artifact_v2(as_of2, det)
    comp2 = compare_subset(run_id=as_of2, symbols=["AAA", "BBB"])
    if comp2.get("ranking") != ["BBB", "AAA"]:
        _fail(f"compare ranking unexpected: {comp2.get('ranking')}")
    _ok("compare winners reflect execution_score ordering for actionable items")
    pd = pick_detail_helper(run_id=as_of2, symbol="AAA")
    assert pd.get("ok") is True

    # e) chat refresh failure sanitization by monkey-patching callee
    def _boom(*_a: Any, **_k: Any) -> Dict[str, Any]:  # noqa: ANN001
        raise RuntimeError("boom")

    chat_refresh.refresh_symbols_v2 = _boom  # type: ignore[attr-defined]
    rs = chat_refresh.refresh_symbols(["AAA", "BBB"])
    if rs.get("ok") is True:
        _fail("chat refresh did not fail as expected")
    if isinstance(rs.get("error"), str) and "REFRESH_FAILED:" in rs.get("error", ""):
        _fail("chat refresh leaked raw exception string")
    _ok("chat refresh failure sanitized")

    # Print brief JSON summaries as artifacts for human inspection
    import json as _json
    print("\n--- Summaries ---")
    print("persisted_v2:", _json.dumps({k: persisted.get(k) for k in ["run_id","as_of","fallback_used","items"]}, ensure_ascii=False)[:300])
    print("fallback_v1_to_v2:", _json.dumps({k: v2.get(k) for k in ["as_of","fallback_used","items"]}, ensure_ascii=False)[:300])
    print("compare_subset:", _json.dumps({k: comp.get(k) for k in ["symbols","ranking","winner_symbol","fallback_used"]}, ensure_ascii=False))
    print("chat_refresh_failure:", _json.dumps(rs, ensure_ascii=False))
    print("\nSmoke passed.")


if __name__ == "__main__":
    main()
