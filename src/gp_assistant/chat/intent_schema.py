from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Literal, Dict, Any


IntentName = Literal[
    "recommend",
    "ask_no_trade_reason",
    "ranking_explain",
    "compare_symbols",
    "analyze_symbol",
    "exit_decision",
    "refresh_recommend",
    "general_explain",
    "unknown",
]


@dataclass
class IntentClassification:
    intent: IntentName = "unknown"
    symbol: Optional[str] = None
    symbols: List[str] = field(default_factory=list)
    ordinal: Optional[int] = None
    query_rewrite: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "symbol": self.symbol,
            "symbols": list(self.symbols or []),
            "ordinal": self.ordinal,
            "query_rewrite": self.query_rewrite,
            "confidence": float(self.confidence or 0.0),
            "reason": self.reason or "",
        }

    @staticmethod
    def from_dict(obj: Dict[str, Any]) -> "IntentClassification":
        ic = IntentClassification()
        try:
            iv = str(obj.get("intent") or "unknown")
            allowed = {
                "recommend",
                "ask_no_trade_reason",
                "ranking_explain",
                "compare_symbols",
                "analyze_symbol",
                "exit_decision",
                "refresh_recommend",
                "general_explain",
                "unknown",
            }
            ic.intent = iv if iv in allowed else "unknown"
        except Exception:
            ic.intent = "unknown"
        try:
            s = obj.get("symbol")
            ic.symbol = str(s) if s is not None and str(s).strip() else None
        except Exception:
            ic.symbol = None
        try:
            syms = obj.get("symbols") or []
            if isinstance(syms, list):
                ic.symbols = [str(x) for x in syms if str(x).strip()]
        except Exception:
            ic.symbols = []
        try:
            ordv = obj.get("ordinal")
            ic.ordinal = int(ordv) if ordv is not None else None
        except Exception:
            ic.ordinal = None
        try:
            q = obj.get("query_rewrite")
            ic.query_rewrite = str(q) if q is not None and str(q).strip() else None
        except Exception:
            ic.query_rewrite = None
        try:
            ic.confidence = float(obj.get("confidence") or 0.0)
        except Exception:
            ic.confidence = 0.0
        try:
            ic.reason = str(obj.get("reason") or "")
        except Exception:
            ic.reason = ""
        return ic

