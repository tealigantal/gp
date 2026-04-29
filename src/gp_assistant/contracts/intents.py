from __future__ import annotations

from typing import Literal

# Primary semantic contract used by the assistant.
# Legacy aliases are still accepted so older tests and fixtures can be normalized
# into the new request model without breaking the runtime.

RequestType = Literal[
    "chat",
    "term_explain",
    "recommend",
    "pick_detail",
    "live_entry_check",
    "no_trade_explain",
    "compare",
    "exit_decision",
    "run_change",
    # legacy aliases
    "explain",
    "live_check",
    "exit",
]

SubjectType = Literal[
    "run",
    "pick",
    "symbol",
    "compare_set",
    "holding",
    "market",
]

FreshnessType = Literal[
    "active_run",
    "latest_5m",
    "rebuild_run",
    "next_session_plan",
    # legacy aliases
    "current_book",
    "rebuild_daybook",
]
