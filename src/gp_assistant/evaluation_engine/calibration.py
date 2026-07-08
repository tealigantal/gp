from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def brier_score(predictions: Iterable[Dict[str, Any]]) -> float:
    rows = list(predictions)
    if not rows:
        return 0.0
    err = 0.0
    n = 0
    for row in rows:
        p = max(0.0, min(1.0, _safe_float(row.get("probability"))))
        y = 1.0 if bool(row.get("success") is True) else 0.0
        err += (p - y) * (p - y)
        n += 1
    return err / max(1, n)


def calibration_curve(predictions: Iterable[Dict[str, Any]], *, buckets: int = 10) -> Dict[str, Any]:
    rows = list(predictions)
    bucket_count = max(1, int(buckets))
    out: List[Dict[str, Any]] = []
    for idx in range(bucket_count):
        lo = idx / bucket_count
        hi = (idx + 1) / bucket_count
        scoped = [
            row
            for row in rows
            if lo <= max(0.0, min(1.0, _safe_float(row.get("probability")))) < hi or (idx == bucket_count - 1 and _safe_float(row.get("probability")) == 1.0)
        ]
        if scoped:
            predicted = sum(_safe_float(row.get("probability")) for row in scoped) / len(scoped)
            realized = sum(1.0 for row in scoped if bool(row.get("success") is True)) / len(scoped)
        else:
            predicted = 0.0
            realized = 0.0
        out.append(
            {
                "bucket": idx,
                "low": lo,
                "high": hi,
                "count": len(scoped),
                "mean_predicted_probability": predicted,
                "realized_win_rate": realized,
            }
        )
    return {
        "brier_score": brier_score(rows),
        "buckets": out,
        "sample_size": len(rows),
    }


def calibration_report(predictions: Iterable[Dict[str, Any]], *, buckets: int = 10) -> Dict[str, Any]:
    rows = list(predictions)
    curve = calibration_curve(rows, buckets=buckets)
    sample_buckets = [
        ("lt_10", 0.0, 10.0),
        ("10_30", 10.0, 30.0),
        ("30_80", 30.0, 80.0),
        ("gte_80", 80.0, float("inf")),
    ]
    effective_sample_buckets: List[Dict[str, Any]] = []
    for label, lo, hi in sample_buckets:
        scoped = [
            row
            for row in rows
            if lo <= _safe_float(row.get("effective_sample_size")) < hi
        ]
        if scoped:
            mean_error = sum(
                abs(max(0.0, min(1.0, _safe_float(row.get("probability")))) - (1.0 if bool(row.get("success") is True) else 0.0))
                for row in scoped
            ) / len(scoped)
            mean_uncertainty = sum(_safe_float(row.get("uncertainty")) for row in scoped) / len(scoped)
        else:
            mean_error = 0.0
            mean_uncertainty = 0.0
        effective_sample_buckets.append(
            {
                "bucket": label,
                "count": len(scoped),
                "mean_absolute_probability_error": mean_error,
                "mean_uncertainty": mean_uncertainty,
            }
        )
    return {
        **curve,
        "effective_sample_buckets": effective_sample_buckets,
    }
