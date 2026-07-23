from __future__ import annotations

from datetime import datetime, time

import pandas as pd

from ..contracts.catalog import MarketPhase, RuntimeDataState
from ..contracts.runtime import MarketGate, RuntimeDataQuality, RuntimeObservation, SymbolExecutionState
from ..providers.factory import get_provider
from ..store import ContractStore
from .publication_service import PublicationService
from .runtime_service import RuntimeService


def market_phase(now: datetime) -> MarketPhase:
    local_time = now.timetz().replace(tzinfo=None)
    if local_time < time(9, 30):
        return MarketPhase.PREOPEN
    if local_time < time(11, 30):
        return MarketPhase.MORNING
    if local_time < time(13, 0):
        return MarketPhase.LUNCH
    if local_time < time(14, 57):
        return MarketPhase.AFTERNOON
    if local_time < time(15, 0):
        return MarketPhase.CLOSING_AUCTION
    return MarketPhase.POSTCLOSE


class RuntimeRecommendationProducer:
    """Reads a fresh spot snapshot for already-selected plan symbols only."""

    def __init__(self, store: ContractStore, *, spot_loader=None):
        self.store = store
        self.spot_loader = spot_loader or (lambda: get_provider(prefer="akshare").get_spot_snapshot())

    def produce(self, *, now: datetime, plan_id: str | None = None) -> RuntimeObservation:
        plan = self.store.load_plan(plan_id) if plan_id else self._current_plan()
        if plan is None:
            raise ValueError("plan_not_found")
        phase = market_phase(now)
        selected = tuple(item for item in plan.evaluated_candidates if item.disposition.value == "selected")
        if plan.market_session_date != now.date():
            return self._commit_and_publish(
                plan=plan,
                now=now,
                phase=phase,
                quality=RuntimeDataQuality(state=RuntimeDataState.UNAVAILABLE, source="akshare:spot", reason_codes=("runtime_session_not_current",)),
                gate=MarketGate(state="deny", score=0.0, reason_codes=("runtime_session_not_current",)),
                states=(),
            )
        if phase not in {MarketPhase.MORNING, MarketPhase.AFTERNOON, MarketPhase.CLOSING_AUCTION}:
            return self._commit_and_publish(
                plan=plan,
                now=now,
                phase=phase,
                quality=RuntimeDataQuality(state=RuntimeDataState.UNAVAILABLE, source="akshare:spot", reason_codes=("market_not_in_trading_phase",)),
                gate=MarketGate(state="deny", score=0.0, reason_codes=("market_not_in_trading_phase",)),
                states=(),
            )
        if not selected:
            return self._commit_and_publish(
                plan=plan,
                now=now,
                phase=phase,
                quality=RuntimeDataQuality(state=RuntimeDataState.UNAVAILABLE, source="akshare:spot", reason_codes=("no_selected_candidate",)),
                gate=MarketGate(state="deny", score=0.0, reason_codes=("no_selected_candidate",)),
                states=(),
            )
        spot = self.spot_loader()
        if not isinstance(spot, pd.DataFrame) or spot.empty or not {"code", "price", "pct_chg"}.issubset(spot.columns):
            return self._commit_and_publish(
                plan=plan,
                now=now,
                phase=phase,
                quality=RuntimeDataQuality(state=RuntimeDataState.UNAVAILABLE, source="akshare:spot", reason_codes=("runtime_snapshot_unavailable",)),
                gate=MarketGate(state="deny", score=0.0, reason_codes=("runtime_snapshot_unavailable",)),
                states=(),
            )
        rows = {str(row.code).zfill(6): row for row in spot[["code", "price", "pct_chg"]].itertuples(index=False)}
        states: list[SymbolExecutionState] = []
        missing = False
        for candidate in selected:
            row = rows.get(candidate.symbol)
            price = float(getattr(row, "price", 0.0) or 0.0) if row is not None else 0.0
            change = float(getattr(row, "pct_chg", 0.0) or 0.0) if row is not None else 0.0
            ready = price > 0.0
            missing = missing or not ready
            states.append(SymbolExecutionState(
                symbol=candidate.symbol,
                state="ready" if ready else "unavailable",
                vwap=None,
                intraday_score=max(-1.0, min(1.0, change / 10.0)) if ready else None,
                reason_codes=() if ready else ("runtime_symbol_missing",),
            ))
        quality = RuntimeDataQuality(
            state=RuntimeDataState.UNAVAILABLE if missing else RuntimeDataState.READY,
            source="akshare:spot",
            reason_codes=("runtime_symbol_missing",) if missing else (),
        )
        gate = MarketGate(
            state="deny" if missing else "allow",
            score=0.0 if missing else 1.0,
            reason_codes=("runtime_symbol_missing",) if missing else (),
        )
        return self._commit_and_publish(plan=plan, now=now, phase=phase, quality=quality, gate=gate, states=tuple(states))

    def _current_plan(self):
        publication = self.store.current_publication()
        return self.store.load_plan(publication.plan_id) if publication else None

    def _commit_and_publish(self, *, plan, now: datetime, phase: MarketPhase, quality: RuntimeDataQuality, gate: MarketGate, states: tuple[SymbolExecutionState, ...]) -> RuntimeObservation:
        observation = RuntimeObservation(
            runtime_id="pending",
            plan_id=plan.plan_id,
            market=plan.market,
            market_session_date=plan.market_session_date,
            observed_at=now,
            slot_closed_at=now,
            market_phase=phase,
            data_quality=quality,
            market_gate=gate,
            symbol_execution_states=states,
            producer_name="real_runtime_producer",
            producer_revision="1",
        )
        runtime = RuntimeService(self.store).observe(observation)
        PublicationService(self.store).publish(plan_id=plan.plan_id, runtime_id=runtime.runtime_id, published_at=now)
        return runtime
