from __future__ import annotations

from gp_assistant.book.daybook import _map_pick, build_daybook
from gp_assistant.runtime.producer import SELECTION_POLICY


def test_explicit_zero_adaptive_score_is_not_replaced_by_a_truthy_fallback():
    pick = _map_pick(
        1,
        {
            "symbol": "600000",
            "adaptive_score": 0.75,
            "adaptive_policy": {
                "adaptive_score": 0.0,
                "decision_score": 0.0,
                "serenity_status": "no_relevant_evidence",
                "serenity_weight": 0.0,
                "serenity_alpha_value": 0.0,
                "serenity_adjustment": 0.0,
            },
        },
    )

    assert pick.scores["adaptive"] == 0.0
    assert pick.scores["final"] == 0.0


def test_incomplete_native_target_cannot_leak_baseline_candidates(monkeypatch):
    raw_candidate = {
        "symbol": "600000",
        "adaptive_score": 0.8,
        "adaptive_policy": {"adaptive_score": 0.8, "decision_score": 0.8},
    }
    monkeypatch.setattr(
        "gp_assistant.book.daybook.build_day_selection",
        lambda *_args, **_kwargs: {
            "debug": {"selection_policy": SELECTION_POLICY},
            "decision": "no_trade",
            "reason": "serenity_coverage_incomplete",
            "tradeable": False,
            "serenity_native_ready": False,
            "serenity_target_id": "target-pending",
            "picks": [raw_candidate],
            "candidate_pool": [raw_candidate],
        },
    )

    daybook = build_daybook("20260714", topk=1, reserve_count=1)

    assert daybook.picks == []
    assert daybook.reserve_picks == []
    assert daybook.reserve_symbols == []
    assert daybook.source_meta["serenity_native_ready"] is False
