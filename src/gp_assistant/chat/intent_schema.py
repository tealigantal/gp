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


# ---------------- Planner v2 (strict plan for tri-phase orchestrator) ----------------

PlannerIntent = Literal[
    "recommend_topn",
    "explain_no_trade",
    "analyze_symbol",
    "analyze_nth_pick",
    "compare_symbols",
    "exit_decision",
    "explain_ranking",
    "explain_run_change",
    "risk_points",
    "clarify_tradeability",
    "refresh_recommend",
    "general_explain",
    "unknown",
]


@dataclass
class PlannerPlan:
    intent: PlannerIntent = "unknown"
    symbol: Optional[str] = None
    symbols: List[str] = field(default_factory=list)
    ordinal: Optional[int] = None
    topk: Optional[int] = None
    force_refresh: bool = False
    reuse_active_run: bool = True
    response_card_kind: str = "text"  # recommendation | no_trade | pick_detail | compare | exit_decision | run_change | status | text
    focus_symbol: Optional[str] = None
    compare_symbols: List[str] = field(default_factory=list)
    explanation_target: Optional[str] = None  # ranking | no_trade | run_change | tradeability | risk | general | None
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "symbol": self.symbol,
            "symbols": list(self.symbols or []),
            "ordinal": int(self.ordinal) if self.ordinal is not None else None,
            "topk": int(self.topk) if self.topk is not None else None,
            "force_refresh": bool(self.force_refresh),
            "reuse_active_run": bool(self.reuse_active_run),
            "response_card_kind": str(self.response_card_kind or "text"),
            "focus_symbol": self.focus_symbol,
            "compare_symbols": list(self.compare_symbols or []),
            "explanation_target": self.explanation_target,
            "confidence": float(self.confidence or 0.0),
            "reason": str(self.reason or ""),
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "PlannerPlan":
        def _bool(v: Any, default: bool = False) -> bool:
            if isinstance(v, bool):
                return v
            s = str(v).strip().lower()
            if s in {"1", "true", "on", "yes"}:
                return True
            if s in {"0", "false", "off", "no"}:
                return False
            return default

        intent = str(d.get("intent") or "unknown")
        allowed = {
            "recommend_topn",
            "explain_no_trade",
            "analyze_symbol",
            "analyze_nth_pick",
            "compare_symbols",
            "exit_decision",
            "explain_ranking",
            "explain_run_change",
            "risk_points",
            "clarify_tradeability",
            "refresh_recommend",
            "general_explain",
            "unknown",
        }
        if intent not in allowed:
            intent = "unknown"
        symbol = d.get("symbol")
        if symbol is not None:
            symbol = str(symbol)
        symbols = [str(s) for s in (d.get("symbols") or []) if str(s)]
        ordinal = d.get("ordinal")
        try:
            ordinal = int(ordinal) if ordinal is not None else None
        except Exception:
            ordinal = None
        topk = d.get("topk")
        try:
            topk = int(topk) if topk is not None else None
        except Exception:
            topk = None
        force_refresh = _bool(d.get("force_refresh"), False)
        reuse_active_run = _bool(d.get("reuse_active_run"), True)
        response_card_kind = str(d.get("response_card_kind") or "text")
        focus_symbol = d.get("focus_symbol")
        if focus_symbol is not None:
            focus_symbol = str(focus_symbol)
        compare_symbols = [str(s) for s in (d.get("compare_symbols") or []) if str(s)]
        explanation_target = d.get("explanation_target")
        if explanation_target is not None:
            explanation_target = str(explanation_target)
        try:
            confidence = float(d.get("confidence") or 0.0)
        except Exception:
            confidence = 0.0
        reason = str(d.get("reason") or "")
        return PlannerPlan(
            intent=intent,
            symbol=symbol,
            symbols=symbols,
            ordinal=ordinal,
            topk=topk,
            force_refresh=force_refresh,
            reuse_active_run=reuse_active_run,
            response_card_kind=response_card_kind,
            focus_symbol=focus_symbol,
            compare_symbols=compare_symbols,
            explanation_target=explanation_target,
            confidence=confidence,
            reason=reason,
        )

