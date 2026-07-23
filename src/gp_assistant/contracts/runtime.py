from __future__ import annotations

from datetime import date, datetime

from .base import ContractModel
from .catalog import MarketPhase, RuntimeDataState
from .market import MarketId


class RuntimeDataQuality(ContractModel):
    state: RuntimeDataState
    source: str
    reason_codes: tuple[str, ...]


class MarketGate(ContractModel):
    state: str
    score: float
    reason_codes: tuple[str, ...]


class SymbolExecutionState(ContractModel):
    symbol: str
    state: str
    vwap: float | None
    intraday_score: float | None
    reason_codes: tuple[str, ...]


class RuntimeObservation(ContractModel):
    runtime_id: str
    plan_id: str
    market: MarketId
    market_session_date: date
    observed_at: datetime
    slot_closed_at: datetime | None
    market_phase: MarketPhase
    data_quality: RuntimeDataQuality
    market_gate: MarketGate
    symbol_execution_states: tuple[SymbolExecutionState, ...]
    producer_name: str
    producer_revision: str
