from __future__ import annotations

"""
Legacy compatibility helpers for historical chat flow.

Note: mainline does not use this module. Kept thin for backwards imports.
"""

from typing import Any, Dict, List, Optional, Tuple

from . import session_store as store


def get_active_run(session_id: str) -> Tuple[Optional[str], List[str]]:
    st = store.get_state(session_id)
    run_id = st.get("active_run_id")
    symbols = list(st.get("active_symbols") or [])
    return (run_id, symbols)


def require_active_run_or_fail(session_id: str) -> Tuple[str, List[str]]:
    run_id, symbols = get_active_run(session_id)
    if not run_id:
        raise RuntimeError("NO_ACTIVE_RUN")
    return str(run_id), symbols


def resolve_symbol_from_ordinal(symbols: List[str], n: int) -> Optional[str]:
    if not isinstance(n, int) or n < 1:
        return None
    if not symbols or len(symbols) < n:
        return None
    return symbols[n - 1]
