from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date, datetime
from pathlib import Path
from typing import Iterable, Optional, Tuple
import re


def parse_user_date(text: str, now: _date) -> Optional[_date]:
    t = text.strip()
    # Chinese month-day: 2月9日 / 02月09日 / 2 月 9 日
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", t)
    if m:
        mm, dd = int(m.group(1)), int(m.group(2))
        return _safe_date(now.year, mm, dd)
    # Chinese numerals month-day: 二月九日 / 十一月二日（简单覆盖）
    m = re.search(r"([一二三四五六七八九十两]{1,3})\s*月\s*([一二三四五六七八九十两]{1,3})\s*日", t)
    if m:
        mm = _cnnum_to_int(m.group(1))
        dd = _cnnum_to_int(m.group(2))
        if mm and dd:
            return _safe_date(now.year, mm, dd)
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


def _cnnum_to_int(s: str) -> Optional[int]:
    m = {'零':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
    if not s:
        return None
    # 支持到 1-31 / 1-12 的范围，解析 十/二十/二十一 等
    total = 0
    if s == '十':
        return 10
    if '十' in s:
        parts = s.split('十')
        hi = parts[0]
        lo = parts[1] if len(parts) > 1 else ''
        tens = m.get(hi, 1) if hi != '' else 1
        ones = m.get(lo, 0) if lo != '' else 0
        total = tens * 10 + ones
    else:
        # 单个数字
        total = 0
        for ch in s:
            if ch in m:
                total = total*10 + m[ch]
            else:
                return None
    return total if total > 0 else None


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
