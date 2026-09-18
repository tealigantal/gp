"""Smoothed unconditional gain/loss score, not a win probability.

All returns and costs are fractions. The common reference is frozen offline;
production never estimates it from today's candidates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
import math

from ..core.paths import configs_dir

REVISION = "daily_score_v6_smoothed_gain_loss"
ROUND_TRIP_COST = 0.003


def score_candidate(*, gain: float, loss: float, support: float,
                    a0: float, n0: float = 20.0) -> dict:
    """(N*G + .5*n0*A0) / (N*(G+L) + n0*A0), scaled to avoid overflow."""
    values = (gain, loss, support, a0, n0)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("nonfinite_ranking_input")
    if gain < 0 or loss < 0 or support <= 0 or a0 <= 0 or n0 <= 0:
        raise ValueError("invalid_gain_loss_scoring_input")
    scale = max(gain, loss, a0)
    weight_scale = max(support, n0)
    g, l, a = gain / scale, loss / scale, a0 / scale
    n, prior = support / weight_scale, n0 / weight_scale
    denominator = n * (g + l) + prior * a
    if denominator <= 0:
        raise ValueError("gain_loss_scoring_underflow")
    score = (n * g + 0.5 * prior * a) / denominator
    return {"score": score, "expected_net_return": gain - loss,
            "reason_codes": () if gain > loss else ("nonpositive_net_edge",)}


@dataclass(frozen=True)
class ScoringPolicy:
    a0: float
    n0: float
    digest: str
    frozen_at: datetime
    evidence_date: date


def scoring_policy_digest() -> str:
    payload = json.loads((configs_dir() / "daily_scoring.json").read_text(encoding="utf-8"))
    return _policy_digest(payload)


def _policy_digest(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_scoring_policy(*, evidence_day: str, known_at: datetime) -> ScoringPolicy:
    path = configs_dir() / "daily_scoring.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("revision") != REVISION or payload.get("round_trip_cost") != ROUND_TRIP_COST:
        raise ValueError("scoring_policy_mismatch")
    if payload.get("a0") is None:
        raise ValueError("scoring_reference_unavailable")
    a0, n0 = float(payload["a0"]), float(payload["n0"])
    score_candidate(gain=0., loss=0., support=1., a0=a0, n0=n0)
    reference = payload["reference"]
    frozen_at = datetime.fromisoformat(reference["frozen_at"])
    reference_day = date.fromisoformat(reference["evidence_date"])
    if (frozen_at.tzinfo is None or known_at.tzinfo is None
            or frozen_at > known_at or reference_day > date.fromisoformat(evidence_day)):
        raise ValueError("scoring_reference_not_yet_available")
    if reference["case_count"] <= 0 or not reference["source_digest"]:
        raise ValueError("scoring_reference_invalid")
    return ScoringPolicy(a0, n0, _policy_digest(payload), frozen_at, reference_day)
