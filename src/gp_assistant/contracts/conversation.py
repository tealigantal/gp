from __future__ import annotations

from datetime import datetime

from .base import ContractModel


class ConversationSession(ContractModel):
    session_id: str
    active_publication_id: str
    created_at: datetime
    updated_at: datetime


class ConversationTurn(ContractModel):
    turn_id: str
    session_id: str
    publication_id: str
    sequence: int
    role: str
    content: str
    created_at: datetime
    client_turn_id: str | None = None
