from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, Optional, Tuple, List
import re


@dataclass
class SessionState:
    default_date: Optional[str] = None
    cash_available: Optional[float] = None
    positions: Dict[str, int] = field(default_factory=dict)  # code or ts_code -> shares
    risk_pref: Optional[str] = None
    default_topk: int = 5
    default_template: str = 'momentum_v1'
    default_mode: str = 'auto'
    exclusions: List[str] = field(default_factory=list)
    no_holdings: bool = False
    last_pick: Optional[dict] = None

    def summary(self) -> str:
        pos = ','.join([f"{k}:{v}" for k,v in self.positions.items()]) or '-'
        return f"date={self.default_date or '-'}, cash={self.cash_available if self.cash_available is not None else '-'}, topk={self.default_topk}, tpl={self.default_template}, mode={self.default_mode}, positions={{ {pos} }}, risk={self.risk_pref or '-'}, excl={len(self.exclusions)}, no_holdings={self.no_holdings}"


def _parse_cash(text: str) -> Optional[float]:
    t = text.replace(',', '')
    # Prefer numbers explicitly tied to cash keywords
    m = re.findall(r"(可用资金|现金|资金|余额)\s*([0-9]+(?:\.[0-9]+)?)\s*([wW万]?)[元块币]?", t)
    if m:
        _, num, unit = m[-1]
        val = float(num)
        if unit in ('w','W','万'):
            val *= 10000.0
        return val
    # Fallback: numbers with explicit w/万 suffix (avoid dates)
    m2 = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*([wW万])", t)
    if m2:
        num, unit = m2[-1]
        val = float(num)
        if unit in ('w','W','万'):
            val *= 10000.0
        return val
    return None


def _find_codes(fragment: str) -> List[str]:
    out: List[str] = []
    # ts_code like 000001.SZ or 600000.SH
    m = re.findall(r"\b(\d{6}\.(?:SZ|SH))\b", fragment, flags=re.IGNORECASE)
    out.extend([x.upper() for x in m])
    # bare 6-digit code
    m2 = re.findall(r"\b(\d{6})\b", fragment)
    out.extend(m2)
    return out


def _parse_positions(text: str) -> Dict[str, int]:
    pos: Dict[str, int] = {}
    # patterns like: 200股科士达002518, 100股紫金矿业601899, 800股黄金ETF518880
    # also allow spaces / commas / Chinese comma
    parts = re.split(r"[，,\n]+", text)
    for p in parts:
        m = re.search(r"(\d+)\s*股", p)
        if not m:
            continue
        qty = int(m.group(1))
        codes = _find_codes(p)
        if not codes:
            # try code trailing in word (e.g., 黄金ETF518880)
            m2 = re.search(r"(\d{6})$", p.strip())
            if m2:
                codes = [m2.group(1)]
        for c in codes:
            pos[c] = qty
    return pos


def _parse_date(text: str) -> Optional[str]:
    t = text.strip()
    m = re.search(r"(20\d{2})[-/ ]?(\d{2})[-/ ]?(\d{2})", t)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return None


def _parse_risk(text: str) -> Optional[str]:
    if any(k in text for k in ['稳健','保守','conservative']):
        return 'conservative'
    if any(k in text for k in ['激进','aggressive']):
        return 'aggressive'
    if any(k in text for k in ['短线','trader']):
        return 'short-term'
    if any(k in text for k in ['低吸','回踩']):
        return 'pullback'
    return None


def update_state_from_text(state: SessionState, text: str) -> Dict[str, object]:
    delta: Dict[str, object] = {}
    c = _parse_cash(text)
    if c is not None:
        state.cash_available = c
        delta['cash_available'] = c
    d = _parse_date(text)
    if d:
        state.default_date = d
        delta['default_date'] = d
    pos = _parse_positions(text)
    if pos:
        # merge positions (override same code)
        state.positions.update(pos)
        delta['positions'] = pos
    r = _parse_risk(text)
    if r:
        state.risk_pref = r
        delta['risk_pref'] = r
    # topk variants: top5 / Top 5 / 前5
    tk = None
    m = re.search(r"(?:top\s*|Top\s*|TOP\s*|前\s*)(\d+)", text)
    if m:
        try:
            tk = int(m.group(1))
        except Exception:
            tk = None
    if tk:
        state.default_topk = tk
        delta['default_topk'] = tk
    return delta


def apply_defaults(date: Optional[str], topk: Optional[int], template: Optional[str], mode: Optional[str], state: SessionState) -> Tuple[str, int, str, str]:
    dd = date or state.default_date or ''
    tk = int(topk or state.default_topk or 5)
    tpl = template or state.default_template or 'momentum_v1'
    md = mode or state.default_mode or 'auto'
    return dd, tk, tpl, md
