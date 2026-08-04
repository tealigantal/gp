from __future__ import annotations

"""Internal classification for missing daily evidence.

This module deliberately returns the existing market-run reason vocabulary.
It does not introduce a public contract or decide a recommendation by itself.
"""

from datetime import date
from typing import Mapping


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
