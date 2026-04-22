from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AssistantBundle:
    conversation_id: str
    text: str
    cards: List[Dict[str, Any]] = field(default_factory=list)
    right_panel: Dict[str, Any] = field(default_factory=dict)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    grounding: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(cls, **kwargs: Any) -> "AssistantBundle":
        return cls(**kwargs)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "text": self.text,
            "cards": self.cards,
            "right_panel": self.right_panel,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
            "grounding": self.grounding,
        }
