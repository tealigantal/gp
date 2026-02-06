from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date, datetime
from pathlib import Path
from typing import Iterable, Optional, Tuple
import re


def parse_user_date(text: str, now: _date) -> Optional[_date]:
    t = text.strip()
    # 8 digits: YYYYMMDD
    m = re.search(r"\b(20\d{2})(\d{2})(\d{2})\b", t)
    if m:
        y, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _safe_date(y, mm, dd)
    # 10 with separators
    m = re.search(r"\b(20\d{2})[-\/]?(\d{1,2})[-\/]?(\d{1,2})\b", t)
    if m:
        y, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _safe_date(y, mm, dd)
    # 4 digits or M/D like 0209, 2/9, 02-09
    m = re.search(r"\b(\d{1,2})[\/-]?(\d{1,2})\b", t)
    if m:
        mm, dd = int(m.group(1)), int(m.group(2))
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            return _safe_date(now.year, mm, dd)
    return None


def _safe_date(y: int, m: int, d: int) -> Optional[_date]:
    try:
        return _date(y, m, d)
    except Exception:
        return None


@dataclass
class EffectiveDate:
    requested: Optional[str]
    effective: str
    reason: Optional[str]


def resolve_effective_date(requested: Optional[str], available_dates: Iterable[str]) -> EffectiveDate:
    av = sorted(set(str(x) for x in available_dates))
    if requested:
        if requested in av:
            return EffectiveDate(requested=requested, effective=requested, reason=None)
        # fallback to nearest past available
        past = [d for d in av if d <= requested]
        if past:
            eff = past[-1]
            return EffectiveDate(requested=requested, effective=eff, reason=f"candidate pool not found for {requested}; fallback to latest available <= requested")
        if av:
            eff = av[-1]
            return EffectiveDate(requested=requested, effective=eff, reason=f"candidate pool not found for {requested}; fallback to latest available in repo")
        # none available
        return EffectiveDate(requested=requested, effective=requested, reason="no candidate pools available; please build one")
    # no requested
    if av:
        return EffectiveDate(requested=None, effective=av[-1], reason=None)
    # none available
    today = datetime.utcnow().strftime('%Y%m%d')
    return EffectiveDate(requested=None, effective=today, reason="no candidate pools available; please build one")

