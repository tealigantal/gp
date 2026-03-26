from __future__ import annotations

from typing import Any, Dict

from .context_engine import build_context
from ..llm.interpret import parse_turn_frame
from ..contracts.objects import MarketBook, TurnFrame


def parse_concern(memory_ctx: Dict[str, Any], book: MarketBook, user_message: str) -> TurnFrame:
    context = build_context(memory_ctx, book)
    return parse_turn_frame(context, user_message)
