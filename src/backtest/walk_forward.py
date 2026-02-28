from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WalkForwardConfig:
    train_window_days: int = 60
    test_window_days: int = 20


def run_walk_forward(config: WalkForwardConfig) -> None:  # pragma: no cover - placeholder
    # Reserved for future: iterate windows, select params per training, evaluate on test
    pass

