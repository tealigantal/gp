from __future__ import annotations

from typing import Any, Dict, List, Set


class ValidationError(Exception):
    pass


def _extract_symbols_from_text(text: str) -> Set[str]:
    import re
    syms = set(re.findall(r"\b(\d{6})\b", text or ""))
    return syms


def _collect_symbols_from_cards(cards: List[Dict[str, Any]]) -> Set[str]:
    out: Set[str] = set()
    for c in cards or []:
        try:
            t = (c or {}).get("type") or c.get("kind")
            if t == "recommendation":
                for it in (c.get("items") or []):
                    s = (it or {}).get("symbol")
                    if s:
                        out.add(str(s))
            elif t in {"pick_detail", "exit_decision"}:
                s = c.get("symbol")
                if s:
                    out.add(str(s))
            elif t == "compare":
                for s in (c.get("symbols") or []):
                    if s:
                        out.add(str(s))
        except Exception:
            continue
    return out


def SymbolConsistencyValidator(
    *,
    final_text: str,
    cards: List[Dict[str, Any]],
    allowed_symbols: List[str],
    user_explicit_symbols: List[str],
) -> None:
    allow: Set[str] = set([str(s) for s in (allowed_symbols or []) if s]) | set([str(s) for s in (user_explicit_symbols or []) if s])
    in_text = _extract_symbols_from_text(final_text or "")
    in_cards = _collect_symbols_from_cards(cards or [])
    extra = (in_text | in_cards) - allow
    if extra:
        raise ValidationError(f"symbols_out_of_scope: {sorted(list(extra))}")


def TradeabilityConsistencyValidator(
    *,
    tradeable: bool | None,
    run_gating: Dict[str, Any] | None,
    final_text: str,
    cards: List[Dict[str, Any]],
) -> None:
    gate_decision = None
    try:
        gate_decision = (run_gating or {}).get("decision")
    except Exception:
        pass
    if tradeable is False or (gate_decision and gate_decision != "allow"):
        s = (final_text or "").lower()
        illegal_kws = ["买入", "建仓", "分笔建仓", "推荐买入"]
        if any(k in s for k in illegal_kws):
            raise ValidationError("buy_semantics_not_allowed_when_no_trade")
        for c in (cards or []) or []:
            try:
                badge = (c or {}).get("badge") or (c or {}).get("action")
                if badge and str(badge).upper() == "BUY":
                    raise ValidationError("buy_badge_not_allowed_when_no_trade")
            except Exception:
                continue


def GroundingRequiredValidator(*, tool_results: List[Dict[str, Any]]) -> None:
    if not tool_results or len(tool_results) == 0:
        raise ValidationError("missing_tool_grounding")

