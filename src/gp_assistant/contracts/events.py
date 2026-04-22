from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class SideResultEvent(BaseModel):
    event_id: str
    session_id: Optional[str] = None
    symbol: Optional[str] = None
    kind: str
    title: str
    body: str
    refs: Dict[str, Any] = Field(default_factory=dict)
