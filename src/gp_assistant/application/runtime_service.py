from __future__ import annotations

import json

from ..contracts.ids import content_id
from ..contracts.runtime import RuntimeObservation
from ..store import ContractStore


class RuntimeService:
    def __init__(self, store: ContractStore):
        self.store = store

    def observe(self, observation: RuntimeObservation) -> RuntimeObservation:
        plan = self.store.load_plan(observation.plan_id)
        if plan is None:
            raise ValueError("plan_not_found")
        if plan.market != observation.market or plan.market_session_date != observation.market_session_date:
            raise ValueError("runtime_session_mismatch")
        if observation.slot_closed_at and observation.slot_closed_at > observation.observed_at:
            raise ValueError("runtime_slot_invalid")
        allowed = {item.symbol for item in plan.evaluated_candidates}
        if any(item.symbol not in allowed for item in observation.symbol_execution_states):
            raise ValueError("runtime_symbol_outside_plan")
        semantic = observation.model_dump(mode="json", exclude={"runtime_id"})
        canonical = observation.model_copy(update={"runtime_id": content_id("runtime", json.dumps(semantic, sort_keys=True, separators=(",", ":")))})
        self.store.commit_runtime(canonical)
        return canonical
