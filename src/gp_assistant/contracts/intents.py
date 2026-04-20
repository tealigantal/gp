from __future__ import annotations

from typing import Literal

# Controlled value types for intent contract

RequestType = Literal[
    'chat',
    'recommend',
    'explain',
    'live_check',
    'compare',
    'exit',
    'run_change',
]

SubjectType = Literal[
    'run',
    'pick',
    'symbol',
    'compare_set',
    'holding',
    'market',
]

FreshnessType = Literal[
    'current_book',
    'latest_5m',
    'rebuild_daybook',
]

