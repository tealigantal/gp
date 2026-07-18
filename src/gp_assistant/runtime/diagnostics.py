from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..book.repo import load_current_book, load_current_pointer, load_current_slot_artifact
from ..core.config import load_config
from ..core.paths import store_dir
from ..evidence.daily_freshness import (
    daily_freshness_target_fields,
    load_latest_daily_freshness_report,
    resolve_daily_target,
)
from ..runtime.market_clock import compute_market_state
from ..runtime.slot_state import build_runtime_state_snapshot, trade_day_iso
from ..selection_engine.datahub import MarketDataHub

_DEFAULT_DAILY_CHECK_SYMBOLS = ("000001", "600000", "600519")


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _daily_cache_check(symbol: str, *, as_of: str | None) -> dict[str, Any]:
    try:
        df, meta = MarketDataHub().daily_ohlcv(symbol, as_of=as_of, min_len=1, prefer_cache_only=True)
    except Exception as ex:  # noqa: BLE001
        return {"symbol": symbol, "ok": False, "error": f"{type(ex).__name__}: {ex}"}
    last = None
    if df is not None and not df.empty and "date" in df.columns:
        try:
            last = str(df["date"].iloc[-1]).split(" ", 1)[0]
        except Exception:
            last = str(df["date"].iloc[-1])
    return {
        "symbol": symbol,
        "ok": bool(last),
        "last": last,
        "len": int(len(df) if df is not None else 0),
        "source": meta.get("source") if isinstance(meta, dict) else None,
        "target_trading_day": meta.get("target_trading_day") if isinstance(meta, dict) else None,
        "last_item_time": meta.get("last_item_time") if isinstance(meta, dict) else None,
        "prefer_cache_only": True,
    }


def diagnose_runtime_slot_state(*, trade_day: str | None = None, symbols: list[str] | None = None) -> dict[str, Any]:
    cfg = load_config()
    ms = compute_market_state()
    target_day = trade_day_iso(trade_day or getattr(ms, "target_daybook_effective_day", None))
    pointer = load_current_pointer()
    artifact = load_current_slot_artifact()
    book = load_current_book()
    daily_target = daily_freshness_target_fields(
        resolve_daily_target(
            target_day or getattr(ms, "target_daybook_effective_day", None),
            allow_probe=False,
        )
    )
    latest_freshness = load_latest_daily_freshness_report() or {}
    runtime_state = build_runtime_state_snapshot(
        book=book,
        market_state=ms,
        daily_target=daily_target,
        latest_freshness_report=latest_freshness,
        current_artifact=artifact,
        intraday_runtime_enabled=bool(getattr(cfg, "intraday_runtime_enabled", False)),
    )
    provider_meta = dict(getattr(artifact, "provider_meta", {}) or {}) if artifact is not None else {}
    eod_probe = _load_json(store_dir() / "cache" / "runtime" / "eod_daily_probe.json")
    check_symbols = symbols or list(_DEFAULT_DAILY_CHECK_SYMBOLS)
    return {
        "market": {
            "market_phase": ms.market_phase,
            "clock_data_status": ms.data_status,
            "target_daybook_effective_day": ms.target_daybook_effective_day,
            "target_pulse_trade_day": ms.target_pulse_trade_day,
            "target_pulse_slot_at": ms.target_pulse_slot_at,
        },
        "runtime_state": {
            "daily_data_state": runtime_state.daily_data_state,
            "book_freshness": runtime_state.book_freshness,
            "artifact_stage": runtime_state.artifact_stage,
            "artifact_freshness": runtime_state.artifact_freshness,
            "artifact_status": runtime_state.artifact_status,
            "tradeability_state": runtime_state.tradeability_state,
            "artifact_lag_reason": runtime_state.artifact_lag_reason,
            "artifact_lag_fields": runtime_state.artifact_lag_fields,
        },
        "current_pointer": pointer.model_dump() if pointer is not None else None,
        "current_artifact": {
            "artifact_id": getattr(artifact, "artifact_id", None),
            "trade_day": getattr(artifact, "trade_day", None),
            "slot_id": getattr(artifact, "slot_id", None),
            "slot_at": getattr(artifact, "slot_at", None),
            "market_phase": getattr(artifact, "market_phase", None),
            "slot_status": getattr(artifact, "slot_status", None),
            "publish_allowed": getattr(artifact, "publish_allowed", None),
            "daybook_effective_day": getattr(artifact, "daybook_effective_day", None),
            "provider_meta": provider_meta,
        },
        "daily_target": daily_target,
        "daily_freshness_report": latest_freshness,
        "eod_probe_cache": eod_probe,
        "daily_cache_checks": [_daily_cache_check(symbol, as_of=target_day) for symbol in check_symbols],
    }
