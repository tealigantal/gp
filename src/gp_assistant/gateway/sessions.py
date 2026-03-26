from __future__ import annotations

from ..memory.service import get_session_overview


def get_session_payload(session_id: str):
    return get_session_overview(session_id)
