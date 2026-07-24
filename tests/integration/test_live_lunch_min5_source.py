from __future__ import annotations

import pytest

from gp_assistant.intraday.lunch_rebalance import collect_lunch_batch_isolated
from gp_assistant.store import ContractStore


@pytest.mark.integration
def test_current_frozen_top30_and_csi300_form_one_isolated_complete_lunch_batch():
    store = ContractStore()
    publication = store.current_publication()
    assert publication is not None
    plan = store.load_plan(publication.plan_id)
    assert plan is not None
    symbols = tuple(
        candidate.symbol
        for candidate in plan.evaluated_candidates
        if any(expert.expert == "serenity" for expert in candidate.experts)
    )
    assert len(symbols) == 30

    batch = collect_lunch_batch_isolated(
        symbols,
        market_session_date=plan.market_session_date,
        timezone_name="Asia/Shanghai",
        budget_sec=110,
    )

    assert len(batch.bars) == 30
    assert {len(frame) for frame in batch.bars.values()} == {24}
    assert len(batch.benchmark) == 24
    assert batch.slot_closed_at.strftime("%H:%M") == "11:30"
