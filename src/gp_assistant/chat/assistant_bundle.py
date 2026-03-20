from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


def _str_list(v: Optional[List[str]]) -> List[str]:
    if not isinstance(v, list):
        return []
    out: List[str] = []
    for x in v:
        try:
            s = str(x)
            if s:
                out.append(s)
        except Exception:
            continue
    return out


def _card(type_: str, title: str, data: Dict[str, Any], *, focus_symbol: Optional[str] = None, symbols: Optional[List[str]] = None, run_id: Optional[str] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "type": str(type_),
        "title": str(title or ""),
        "data": dict(data or {}),
    }
    if focus_symbol:
        out["focus_symbol"] = str(focus_symbol)
    if symbols:
        out["symbols"] = _str_list(symbols)
    if run_id:
        out["run_id"] = str(run_id)
    return out


@dataclass
class AssistantBundle:
    id: Optional[str]
    conversation_id: str
    seq: Optional[int]
    role: str
    kind: str

    # Canonical user-visible fields
    text: str
    cards: List[Dict[str, Any]]
    right_panel: Dict[str, Any]

    # Grounding + provenance
    tool_calls: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]
    grounding: Dict[str, Any]

    @staticmethod
    def build(
        *,
        conversation_id: str,
        text: str,
        cards: Optional[List[Dict[str, Any]]] = None,
        right_panel: Optional[Dict[str, Any]] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_results: Optional[List[Dict[str, Any]]] = None,
        grounding: Optional[Dict[str, Any]] = None,
    ) -> "AssistantBundle":
        return AssistantBundle(
            id=None,
            conversation_id=conversation_id,
            seq=None,
            role="assistant",
            kind="assistant_bundle",
            text=str(text or ""),
            cards=list(cards or []),
            right_panel=dict(right_panel or {}),
            tool_calls=list(tool_calls or []),
            tool_results=list(tool_results or []),
            grounding=dict(grounding or {}),
        )

    def to_payload(self) -> Dict[str, Any]:
        # Strict schema normalization for persistence
        rp = dict(self.right_panel or {})
        g = dict(self.grounding or {})
        # normalize some common fields
        g.setdefault("source", "tool_calling_agent")
        rp.setdefault("active_run_id", g.get("active_run_id"))
        rp.setdefault("previous_run_id", g.get("previous_run_id"))
        rp.setdefault("focus_symbol", g.get("focus_symbol"))
        rp.setdefault("active_symbols", g.get("active_symbols"))
        rp.setdefault("tradeable", g.get("tradeable"))
        rp.setdefault("run_gating", g.get("run_gating"))
        rp.setdefault("reused_run", g.get("reused_run"))
        rp.setdefault("stale", g.get("stale"))
        rp.setdefault("refresh_reason", g.get("refresh_reason"))

        return {
            "kind": "assistant_bundle",
            "text": str(self.text or ""),
            # canonical card view-models only; do not rely on tool_results/right_panel to push UI
            "cards": list(self.cards or []),
            "right_panel": rp,
            "tool_calls": list(self.tool_calls or []),
            "tool_results": list(self.tool_results or []),
            "grounding": {
                "source": str(g.get("source") or "tool_calling_agent"),
                "active_run_id": g.get("active_run_id"),
                "previous_run_id": g.get("previous_run_id"),
                "focus_symbol": g.get("focus_symbol"),
                "active_symbols": _str_list(g.get("active_symbols")),
                "used_symbols": _str_list(g.get("used_symbols")),
                "tradeable": bool(g.get("tradeable")) if g.get("tradeable") is not None else None,
                "run_gating": g.get("run_gating"),
                "tools_used": _str_list(g.get("tools_used")),
            },
        }

# re-export card builder for agent
Card = _card
