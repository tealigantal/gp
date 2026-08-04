from __future__ import annotations

"""Internal classification for missing daily evidence.

This module deliberately returns the existing market-run reason vocabulary.
It does not introduce a public contract or decide a recommendation by itself.
"""

from datetime import date
import json
from pathlib import Path
from typing import Mapping

from ..core.paths import store_dir


def classify_missing_daily(
    *,
    symbol: str,
    trade_date: date,
    error: str | None = None,
    instrument: Mapping[str, object] | None = None,
) -> tuple[str, str]:
    """Return ``(disposition, existing_reason)`` for a missing target bar.

    Lifecycle facts are evaluated for the requested date, never from a
    current mutable status.  Unknown or provider failures remain retryable;
    they must not be converted into suspension evidence.
    """
    del symbol
    day = trade_date.isoformat()
    info = instrument or {}
    listed_from = str(info.get("listed_from") or "")[:10]
    listed_to = str(info.get("listed_to") or "")[:10]
    if listed_from and day < listed_from:
        return "excluded", "pre_listing"
    if listed_to and day > listed_to:
        return "excluded", "delisted"

    message = str(error or "").lower()
    if any(token in message for token in ("connection", "timeout", "remote", "http")):
        return "retry", "provider_unavailable"
    if any(token in message for token in ("empty", "no rows", "not found")):
        return "retry", "provider_empty"
    if any(token in message for token in ("date", "schema", "column", "parse", "invalid")):
        return "retry", "provider_payload_invalid"
    return "retry", "target_date_missing"


def lifecycle_exclusions(*, trade_date: date, symbols: tuple[str, ...]) -> dict[str, dict[str, object]]:
    """Load date-bound lifecycle facts and return existing exclusion payloads.

    The sidecar is operational evidence, not a replacement product contract.
    Missing or malformed sidecars fail closed and leave symbols retryable.
    """
    path = store_dir() / "universe" / "instrument_lifecycle.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload.get("records", []) if isinstance(payload, Mapping) else []
    except (OSError, ValueError, TypeError):
        return {}
    target = trade_date.isoformat()
    wanted = set(symbols)
    output: dict[str, dict[str, object]] = {}
    for item in records:
        if not isinstance(item, Mapping):
            continue
        symbol = str(item.get("symbol") or "").zfill(6)
        if symbol not in wanted:
            continue
        start = str(item.get("effective_from") or "")[:10]
        end = str(item.get("effective_to") or "")[:10]
        if start and target < start or end and target > end:
            continue
        reason = str(item.get("reason") or "")
        if reason not in {"pre_listing", "delisted"}:
            continue
        output[symbol] = {
            "symbol": symbol,
            "trade_date": target,
            "state": "excluded",
            "reason": reason,
            "source": str(item.get("source") or "instrument_lifecycle"),
            "source_url": str(item.get("source_url") or ""),
            "evidence": str(item.get("evidence") or ""),
        }
    return output
