from __future__ import annotations

"""
Offline contract self-checks to ensure strict, provenance-rich outputs.

This module avoids network and uses dev fixtures to build a synthetic payload,
then enforces the contract by normalizing and validating meta/data_status.
"""

from typing import Any, Dict, List

import os

from .compact_payload import compact_recommend_meta
from .strict_output import normalize_payload
from ..dev.fixtures import dev_recommend_payload, dev_ohlcv_bars
from ..core.strict import is_strict


def _build_payload_for_contract() -> Dict[str, Any]:
    payload = dev_recommend_payload(topk=2)
    # enrich picks with last_close/last_date (deterministic, offline)
    picks = payload.get("picks") or []
    for it in picks:
        sym = str(it.get("symbol"))
        bars, meta = dev_ohlcv_bars(sym, limit=60)
        if bars:
            it["last_close"] = float(bars[-1]["close"]) if "close" in bars[-1] else None
            it["last_date"] = str(bars[-1].get("date"))
    # No pseudo themes/hints here; use provided themes
    payload.setdefault("mover_hints", [])
    # fabricate minimal data_status that reflects offline dev
    payload["data_status"] = {
        "snapshot": {"ok": False, "source": None, "rows": 0, "elapsed_sec": None, "cache": "none", "as_of_ts": None, "error": "dev_no_snapshot"},
        "themes": {"ok": bool(payload.get("themes")), "source": None, "attempted": [], "error": None, "as_of_ts": None},
        "daily": {"ok": True, "symbols_ok": len(picks), "symbols_fail": 0, "error_summary": None},
    }
    return payload


def main() -> int:
    # enforce strict by default
    os.environ.setdefault("GP_STRICT_OUTPUT", "1")
    payload = _build_payload_for_contract()
    payload = normalize_payload(payload)
    meta = compact_recommend_meta(payload)

    # checks
    assert meta.get("schema_version") == 1
    ds = meta.get("data_status") or {}
    assert isinstance(ds, dict)
    assert isinstance(ds.get("snapshot"), dict)
    assert isinstance(meta.get("themes"), list)
    if not (ds.get("snapshot") or {}).get("ok"):
        # snapshot not ok -> no mover hints in meta
        assert not meta.get("mover_hints")
    # strict picks: ensure last_close and bands are not fabricated (checked via normalize)
    # not part of meta; but payload normalization ensures no pseudo picks
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

