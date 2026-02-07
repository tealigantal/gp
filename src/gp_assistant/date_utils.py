from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date, datetime
from typing import Iterable, Optional
import re


def parse_user_date(text: str, now: _date) -> Optional[_date]:
    """Parse a user-provided date from free text.
    Supported:
    - YYYYMMDD / YYYY-MM-DD / YYYY/MM/DD
    - MMDD (0209)
    - M/D 或 M-D（2/9, 02-09）
    - 中文：2月9日 / 02月09日 / 二月九日 / 十一月二日
    年份未提供时默认使用当前年份。
    """
    t = text.strip()
    # YYYYMMDD
    m = re.search(r"\b(20\d{2})(\d{2})(\d{2})\b", t)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # YYYY-MM-DD / YYYY/MM/DD
    m = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", t)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # MMDD
    m = re.search(r"\b(\d{2})(\d{2})\b", t)
    if m:
        mm, dd = int(m.group(1)), int(m.group(2))
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            return _safe_date(now.year, mm, dd)
    # M/D or M-D
    m = re.search(r"\b(\d{1,2})[\/-](\d{1,2})\b", t)
    if m:
        return _safe_date(now.year, int(m.group(1)), int(m.group(2)))
    # 2月9日
    m = re.search(r"\b(\d{1,2})\s*月\s*(\d{1,2})\s*日?\b", t)
    if m:
        return _safe_date(now.year, int(m.group(1)), int(m.group(2)))
    # 二月九日 / 十一月二日
    m = re.search(r"([一二三四五六七八九十两]{1,3})\s*月\s*([一二三四五六七八九十两]{1,3})\s*日?", t)
    if m:
        mm = _cnnum_to_int(m.group(1))
        dd = _cnnum_to_int(m.group(2))
        if mm and dd:
            return _safe_date(now.year, mm, dd)
    return None


def _safe_date(y: int, m: int, d: int) -> Optional[_date]:
    try:
        return _date(y, m, d)
    except Exception:
        return None


def _cnnum_to_int(s: str) -> Optional[int]:
    """Parse basic Chinese numerals up to 31 (含 十/两)。"""
    digit = {'零':0, '〇':0, '一':1, '二':2, '两':2, '三':3, '四':4, '五':5, '六':6, '七':7, '八':8, '九':9}
    if not s:
        return None
    if s == '十':
        return 10
    if '十' in s:
        hi, *rest = s.split('十')
        tens = digit.get(hi, 1) if hi else 1
        ones = digit.get(rest[0], 0) if rest and rest[0] else 0
        val = tens*10 + ones
        return val if 1 <= val <= 31 else None
    val = 0
    for ch in s:
        if ch not in digit:
            return None
        val = val*10 + digit[ch]
    return val if 1 <= val <= 31 else None


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
        past = [d for d in av if d <= requested]
        if past:
            eff = past[-1]
            return EffectiveDate(requested=requested, effective=eff, reason=f"candidate pool not found for {requested}; fallback to latest available <= requested")
        if av:
            eff = av[-1]
            return EffectiveDate(requested=requested, effective=eff, reason=f"candidate pool not found for {requested}; fallback to latest available in repo")
        return EffectiveDate(requested=requested, effective=requested, reason="no candidate pools available; please build one")
    if av:
        return EffectiveDate(requested=None, effective=av[-1], reason=None)
    today = datetime.utcnow().strftime('%Y%m%d')
    return EffectiveDate(requested=None, effective=today, reason="no candidate pools available; please build one")
