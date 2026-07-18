from __future__ import annotations

from typing import Literal

# Primary semantic contract used by the assistant. Router output is strict:
# retired V1/V2 labels are rejected instead of being translated at runtime.

RequestType = Literal[
    "chat",
    "term_explain",
    "recommend",
    "pick_detail",
    "single_stock_query",
    "live_entry_check",
    "no_trade_explain",
    "compare",
    "candidate_compare",
    "intraday_situation",
    "exit_decision",
    "run_change",
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
    "rebuild_run",
    "next_session_plan",
]
