from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import pandas as pd

from ..core.paths import store_dir
from ..providers.boards import is_mainboard
from ..selection_engine.datahub import MarketDataHub


SCHEMA = "MarketUniverseSnapshot.v1"


@dataclass(frozen=True)
class UniverseThresholds:
    version: str = "full-market-v1"
    minimum_mainboard_count: int = 3000
    previous_count_ratio: float = 0.95
    metadata_coverage_ratio: float = 0.95
    daily_coverage_ratio: float = 0.95
    minimum_eligible_count: int = 50
    scoring_pool_limit: int = 200
    minimum_scored_count: int = 20
    scoring_success_ratio: float = 0.95
    minimum_listing_days: int = 60
    minimum_close: float = 2.0
    maximum_close: float = 500.0
    minimum_average_amount_5d: float = 500_000_000.0
    minimum_daily_bars: int = 120


def _clean_symbol(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if "." in raw:
        raw = raw.split(".", 1)[0]
    for prefix in ("sh", "sz", "bj"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else ""


def _find_column(frame: pd.DataFrame, names: Iterable[str]) -> str | None:
    columns = {str(column).strip().lower(): str(column) for column in frame.columns}
    for name in names:
        found = columns.get(str(name).strip().lower())
        if found:
            return found
    return None


def _iso_date(value: Any) -> str | None:
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).date().isoformat()


def load_exchange_master_frames() -> list[tuple[str, pd.DataFrame]]:
    """Fetch exchange security masters. This function is worker-only."""

    import akshare as ak  # type: ignore

    return [
        ("sse:stock_info_sh_name_code:mainboard_a", ak.stock_info_sh_name_code(symbol="主板A股")),
        ("szse:stock_info_sz_name_code:a_share", ak.stock_info_sz_name_code(symbol="A股列表")),
    ]


def normalize_exchange_master(
    frames: Sequence[tuple[str, pd.DataFrame]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    source_counts: dict[str, int] = {}
    errors: list[str] = []
    for source, frame in frames:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            errors.append(f"{source}:empty")
            continue
        source_counts[source] = int(len(frame))
        code_col = _find_column(frame, ["证券代码", "a股代码", "公司代码", "代码", "code", "symbol"])
        name_col = _find_column(frame, ["证券简称", "a股简称", "公司简称", "名称", "name"])
        listing_col = _find_column(frame, ["上市日期", "a股上市日期", "listing_date", "list_date"])
        if code_col is None:
            errors.append(f"{source}:code_column_missing")
            continue
        for _, record in frame.iterrows():
            symbol = _clean_symbol(record.get(code_col))
            if not symbol or not is_mainboard(symbol):
                continue
            name = str(record.get(name_col) or "").strip() if name_col else ""
            listing_date = _iso_date(record.get(listing_col)) if listing_col else None
            rows[symbol] = {
                "symbol": symbol,
                "name": name or None,
                "listing_date": listing_date,
                "exchange": "SSE" if symbol.startswith("6") else "SZSE",
                "master_source": source,
            }
    normalized = [rows[symbol] for symbol in sorted(rows)]
    return normalized, {
        "sources": source_counts,
        "errors": errors,
        "raw_count": sum(source_counts.values()),
        "mainboard_count": len(normalized),
    }


def _default_daily_loader(
    symbols: Sequence[str],
    as_of: str,
) -> Mapping[str, tuple[pd.DataFrame, Mapping[str, Any]]]:
    hub = MarketDataHub()
    try:
        batch_size = max(1, int(os.getenv("GP_UNIVERSE_BATCH_SIZE", "100")))
    except Exception:
        batch_size = 100
    result: dict[str, tuple[pd.DataFrame, Mapping[str, Any]]] = {}
    for start in range(0, len(symbols), batch_size):
        batch = list(symbols[start : start + batch_size])
        # Each batch is committed to history.db before the next batch starts,
        # making a full-market backfill naturally resumable after interruption.
        result.update(hub.daily_ohlcv_batch(batch, as_of=as_of, safety_lookback_days=365))
    return result


def _content_digest(payload: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _snapshot_root() -> Path:
    root = store_dir() / "universe" / "snapshots"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _latest_previous_accepted_count(day: str) -> int | None:
    root = _snapshot_root()
    for pointer in sorted(root.glob("*/accepted.json"), reverse=True):
        if pointer.parent.name >= str(day):
            continue
        try:
            target = json.loads(pointer.read_text(encoding="utf-8"))
            snapshot_path = root / str(target.get("relative_path") or "")
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            count = int((snapshot.get("counts") or {}).get("mainboard_input_count") or 0)
            if count > 0:
                return count
        except Exception:
            continue
    return None


def load_accepted_market_universe(daybook_effective_day: str) -> dict[str, Any] | None:
    day = str(pd.to_datetime(daybook_effective_day).date().isoformat())
    pointer_path = _snapshot_root() / day / "accepted.json"
    if not pointer_path.exists():
        return None
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        snapshot_path = _snapshot_root() / str(pointer.get("relative_path") or "")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        digest_input = dict(snapshot)
        expected = str(digest_input.pop("content_digest", "") or "")
        digest_input.pop("universe_id", None)
        actual = _content_digest(digest_input)
        if (
            str(snapshot.get("schema") or "") != SCHEMA
            or str(snapshot.get("daybook_effective_day") or "") != day
            or snapshot.get("complete") is not True
            or bool(snapshot.get("fallback_used"))
            or not expected
            or expected != actual
            or str(pointer.get("universe_id") or "") != str(snapshot.get("universe_id") or "")
        ):
            return None
        return snapshot
    except Exception:
        return None


def build_market_universe_snapshot(
    daybook_effective_day: str,
    *,
    observed_at: str | None = None,
    thresholds: UniverseThresholds | None = None,
    master_frames: Sequence[tuple[str, pd.DataFrame]] | None = None,
    daily_loader: Callable[[Sequence[str], str], Mapping[str, tuple[pd.DataFrame, Mapping[str, Any]]]] | None = None,
    previous_accepted_count: int | None = None,
) -> dict[str, Any]:
    """Build a deterministic full-market universe draft without publishing it.

    Network-capable dependencies are explicit so callers can keep this function
    in the worker path and tests can use in-memory fixtures.
    """

    target_day = str(pd.to_datetime(daybook_effective_day).date().isoformat())
    observed = observed_at or datetime.now(timezone.utc).isoformat()
    policy = thresholds or UniverseThresholds()
    master_loader_error = None
    try:
        frames = list(master_frames) if master_frames is not None else load_exchange_master_frames()
        master, master_meta = normalize_exchange_master(frames)
    except Exception as exc:  # noqa: BLE001
        master = []
        master_loader_error = f"{type(exc).__name__}: {exc}"
        master_meta = {
            "sources": {},
            "errors": [master_loader_error],
            "raw_count": 0,
            "mainboard_count": 0,
        }
    previous_count = previous_accepted_count
    if previous_count is None:
        previous_count = _latest_previous_accepted_count(target_day)
    symbols = [str(item["symbol"]) for item in master]
    loader = daily_loader or _default_daily_loader
    try:
        daily_map = dict(loader(symbols, target_day) or {})
        loader_error = None
    except Exception as exc:  # noqa: BLE001
        daily_map = {}
        loader_error = f"{type(exc).__name__}: {exc}"

    target = pd.Timestamp(target_day)
    exclusions = {
        "st_or_delisting": 0,
        "listing_age_lt_60": 0,
        "price_out_of_range": 0,
        "liquidity_below_threshold": 0,
        "history_lt_120": 0,
        "daily_missing_or_stale": 0,
        "metadata_missing": 0,
    }
    metadata_complete = 0
    daily_ready = 0
    eligible: list[dict[str, Any]] = []
    for item in master:
        symbol = str(item["symbol"])
        name = str(item.get("name") or "").strip()
        listing_date = _iso_date(item.get("listing_date"))
        metadata_ok = bool(name and listing_date)
        if metadata_ok:
            metadata_complete += 1
        else:
            exclusions["metadata_missing"] += 1
        frame_meta = daily_map.get(symbol)
        frame = frame_meta[0] if frame_meta else None
        meta = dict(frame_meta[1] or {}) if frame_meta else {}
        if not isinstance(frame, pd.DataFrame) or frame.empty or "date" not in frame.columns:
            exclusions["daily_missing_or_stale"] += 1
            continue
        scoped = frame.copy()
        scoped["date"] = pd.to_datetime(scoped["date"], errors="coerce")
        scoped = scoped.dropna(subset=["date"])
        scoped = scoped[scoped["date"].dt.normalize() <= target].sort_values("date")
        last_date = _iso_date(scoped["date"].iloc[-1]) if not scoped.empty else None
        if last_date != target_day or meta.get("strict_blocked") is True:
            exclusions["daily_missing_or_stale"] += 1
            continue
        daily_ready += 1
        if not metadata_ok:
            continue
        upper_name = name.upper()
        if "ST" in upper_name or "退" in name:
            exclusions["st_or_delisting"] += 1
            continue
        listed = pd.Timestamp(listing_date)
        if int((target - listed).days) < policy.minimum_listing_days:
            exclusions["listing_age_lt_60"] += 1
            continue
        if len(scoped) < policy.minimum_daily_bars:
            exclusions["history_lt_120"] += 1
            continue
        close = float(pd.to_numeric(scoped["close"].iloc[-1], errors="coerce"))
        if not math.isfinite(close) or close < policy.minimum_close or close > policy.maximum_close:
            exclusions["price_out_of_range"] += 1
            continue
        amount_series = scoped["amount"] if "amount" in scoped.columns else pd.Series(dtype=float)
        amounts = pd.to_numeric(amount_series, errors="coerce").tail(5)
        average_amount = float(amounts.mean()) if len(amounts) == 5 else float("nan")
        if not math.isfinite(average_amount) or average_amount < policy.minimum_average_amount_5d:
            exclusions["liquidity_below_threshold"] += 1
            continue
        eligible.append(
            {
                **item,
                "last_date": last_date,
                "close": close,
                "average_amount_5d": average_amount,
                "daily_rows": int(len(scoped)),
                "daily_source": str(meta.get("source") or "unknown"),
            }
        )

    eligible.sort(key=lambda item: (-float(item["average_amount_5d"]), str(item["symbol"])))
    scoring_pool = eligible[: policy.scoring_pool_limit]
    mainboard_count = len(master)
    metadata_ratio = metadata_complete / mainboard_count if mainboard_count else 0.0
    daily_ratio = daily_ready / mainboard_count if mainboard_count else 0.0
    blocking_reasons: list[str] = []
    if mainboard_count < policy.minimum_mainboard_count:
        blocking_reasons.append("mainboard_count_below_absolute_minimum")
    if master_loader_error:
        blocking_reasons.append("exchange_master_load_failed")
    if previous_count and mainboard_count < math.ceil(previous_count * policy.previous_count_ratio):
        blocking_reasons.append("mainboard_count_below_previous_ratio")
    if metadata_ratio < policy.metadata_coverage_ratio:
        blocking_reasons.append("master_metadata_coverage_below_threshold")
    if daily_ratio < policy.daily_coverage_ratio:
        blocking_reasons.append("target_daily_coverage_below_threshold")
    if len(eligible) < policy.minimum_eligible_count:
        blocking_reasons.append("eligible_pool_below_minimum")
    if loader_error:
        blocking_reasons.append("daily_loader_failed")

    return {
        "schema": SCHEMA,
        "universe_id": None,
        "daybook_effective_day": target_day,
        "observed_at": observed,
        "master_sources": master_meta,
        "quote_source": "daily_history_store",
        "data_date": target_day,
        "content_digest": None,
        "thresholds": asdict(policy),
        "counts": {
            "mainboard_input_count": mainboard_count,
            "metadata_complete_count": metadata_complete,
            "daily_ready_count": daily_ready,
            "eligible_count": len(eligible),
            "scoring_pool_count": len(scoring_pool),
            "scored_count": 0,
            "selected_count": 0,
        },
        "coverage": {
            "metadata_ratio": metadata_ratio,
            "daily_ratio": daily_ratio,
            "scoring_success_ratio": 0.0,
        },
        "exclusions": exclusions,
        "scoring_pool": scoring_pool,
        "fallback_used": False,
        "complete": not blocking_reasons,
        "blocking_reason": "candidate_universe_incomplete" if blocking_reasons else None,
        "blocking_reasons": blocking_reasons,
        "loader_error": loader_error,
        "previous_accepted_mainboard_count": previous_count,
    }


def finalize_market_universe_snapshot(
    draft: Mapping[str, Any],
    *,
    scored_count: int,
    selected_count: int,
    persist: bool = True,
) -> dict[str, Any]:
    snapshot = json.loads(json.dumps(dict(draft), ensure_ascii=False, default=str))
    counts = dict(snapshot.get("counts") or {})
    thresholds = dict(snapshot.get("thresholds") or {})
    pool_count = int(counts.get("scoring_pool_count") or 0)
    counts["scored_count"] = max(0, int(scored_count))
    counts["selected_count"] = max(0, int(selected_count))
    snapshot["counts"] = counts
    scoring_ratio = counts["scored_count"] / pool_count if pool_count else 0.0
    coverage = dict(snapshot.get("coverage") or {})
    coverage["scoring_success_ratio"] = scoring_ratio
    snapshot["coverage"] = coverage
    reasons = list(snapshot.get("blocking_reasons") or [])
    minimum_scored = int(thresholds.get("minimum_scored_count") or 20)
    minimum_ratio = float(thresholds.get("scoring_success_ratio") or 0.95)
    if counts["scored_count"] < minimum_scored:
        reasons.append("scored_count_below_minimum")
    if pool_count and scoring_ratio < minimum_ratio:
        reasons.append("scoring_success_ratio_below_threshold")
    snapshot["blocking_reasons"] = list(dict.fromkeys(reasons))
    snapshot["complete"] = not snapshot["blocking_reasons"]
    snapshot["blocking_reason"] = None if snapshot["complete"] else "candidate_universe_incomplete"
    digest_input = dict(snapshot)
    digest_input.pop("universe_id", None)
    digest_input.pop("content_digest", None)
    digest = _content_digest(digest_input)
    snapshot["content_digest"] = digest
    snapshot["universe_id"] = f"mus_{snapshot['daybook_effective_day'].replace('-', '')}_{digest[:20]}"
    if persist:
        day_root = _snapshot_root() / str(snapshot["daybook_effective_day"])
        relative = Path(str(snapshot["daybook_effective_day"])) / f"{snapshot['universe_id']}.json"
        path = _snapshot_root() / relative
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != snapshot:
                raise RuntimeError(f"immutable_market_universe_conflict:{path}")
        else:
            _atomic_json(path, snapshot)
        pointer = {
            "schema": "MarketUniversePointer.v1",
            "universe_id": snapshot["universe_id"],
            "daybook_effective_day": snapshot["daybook_effective_day"],
            "relative_path": str(relative).replace("\\", "/"),
            "updated_at": snapshot["observed_at"],
        }
        _atomic_json(day_root / "attempt.json", pointer)
        if snapshot["complete"]:
            _atomic_json(day_root / "accepted.json", pointer)
            _atomic_json(_snapshot_root() / "current.json", pointer)
    return snapshot


def universe_summary(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    value = dict(snapshot or {})
    return {
        "schema": value.get("schema"),
        "universe_id": value.get("universe_id"),
        "daybook_effective_day": value.get("daybook_effective_day"),
        "data_date": value.get("data_date"),
        "counts": dict(value.get("counts") or {}),
        "coverage": dict(value.get("coverage") or {}),
        "thresholds": dict(value.get("thresholds") or {}),
        "fallback_used": bool(value.get("fallback_used")),
        "complete": bool(value.get("complete")),
        "blocking_reason": value.get("blocking_reason"),
        "blocking_reasons": list(value.get("blocking_reasons") or []),
        "content_digest": value.get("content_digest"),
    }
