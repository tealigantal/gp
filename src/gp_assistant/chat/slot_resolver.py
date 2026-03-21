from __future__ import annotations

"""
Deterministic slot resolver for chat intents.

Rules precedence:
  1) explicit symbol (6-digit) >
  2) ordinal reference (第一只/第二只/第n个/推荐里的第n个) >
  3) collection reference (这几只/这三只/上面那三只/都/全部/推荐里的...) >
  4) focused_symbol reference (这个/那只/这只)

No default-first fallback when ambiguous.
"""

from typing import Any, Dict, List, Optional, Tuple
import re

from . import session_store as store


_RE_CODE = re.compile(r"\b(\d{6})(?:\.(?:SZ|SH))?\b", re.IGNORECASE)


def _ordinal_n_from_text(message: str) -> Optional[int]:
    s = (message or "")
    # explicit n
    m = re.search(r"第\s*(\d+)\s*(?:只|个)", s)
    if m:
        try:
            n = int(m.group(1))
            if n >= 1:
                return n
        except Exception:
            return None
    if any(k in s for k in ["第一只", "第一个", "第1只", "第1个", "first", "1st"]):
        return 1
    if any(k in s for k in ["第二只", "第二个", "第2只", "第2个", "second", "2nd"]):
        return 2
    if any(k in s for k in ["第三只", "第三个", "第3只", "第3个", "third", "3rd"]):
        return 3
    return None


def _is_collection_ref(message: str) -> bool:
    s = (message or "")
    kws = ["这几只", "这三只", "上面那三只", "上面那几只", "都", "全部", "所有", "推荐里的", "上面那", "这几个"]
    return any(k in s for k in kws)


def _explicit_symbols_from_text(message: str) -> List[str]:
    return list(dict.fromkeys(_RE_CODE.findall(message or "")))  # dedup, keep order


def resolve_targets(session_id: str, message: str) -> Dict[str, Any]:
    """Resolve message to a target set or single symbol.

    Returns:
        { kind: 'symbol'|'collection'|'none',
          symbol?: str,
          symbols?: list[str],
          reason: str }
    """
    msg = (message or "").strip()
    # 1) explicit symbol(s)
    codes = _explicit_symbols_from_text(msg)
    if codes:
        # first code as primary; retain as single-symbol action (user specified)
        return {"kind": "symbol", "symbol": codes[0], "reason": "explicit_symbol"}

    # Last known sets
    st = store.get_state(session_id)
    active = list(st.get("active_symbols") or [])
    if not active:
        active = list(st.get("last_recommend_symbols") or [])

    # 2) ordinal reference
    n = _ordinal_n_from_text(msg)
    if n is not None:
        if not active or len(active) < n:
            return {"kind": "none", "reason": "ordinal_out_of_range", "detail": {"n": n, "available": active}}
        return {"kind": "symbol", "symbol": active[n - 1], "reason": f"ordinal_{n}"}

    # 3) collection reference
    if _is_collection_ref(msg):
        if active:
            return {"kind": "collection", "symbols": active, "reason": "collection_active_run"}
        # no active -> safe none (do not default-first)
        return {"kind": "none", "reason": "collection_but_empty"}

    # 4) pronouns -> focused
    pronouns = ["这只", "这票", "刚才那只", "上一只", "那只", "这一个", "这个", "它"]
    if any(k in msg for k in pronouns):
        focus = store.get_focus(session_id)
        if focus:
            return {"kind": "symbol", "symbol": focus, "reason": "pronoun_focus"}
        if active:
            # still avoid silent default-first; require user to clarify
            return {"kind": "none", "reason": "pronoun_no_focus"}
        return {"kind": "none", "reason": "pronoun_but_no_context"}

    return {"kind": "none", "reason": "unresolved"}
