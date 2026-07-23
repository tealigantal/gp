from __future__ import annotations

from .calibration import brier_score, calibration_curve, calibration_report
from .counterfactual import analyze_regret, classify_prediction_error


def run_historical_replay_ab(*args, **kwargs):
    from .historical_replay import run_historical_replay_ab as _run

    return _run(*args, **kwargs)


def save_replay_report(*args, **kwargs):
    from .historical_replay import save_replay_report as _save

    return _save(*args, **kwargs)

__all__ = [
    "analyze_regret",
    "brier_score",
    "calibration_curve",
    "calibration_report",
    "classify_prediction_error",
    "run_historical_replay_ab",
    "save_replay_report",
]
