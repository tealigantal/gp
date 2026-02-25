from __future__ import annotations

from typing import Any, Dict, List


def _fmt_or_na(v: Any, reason: str) -> str:
    try:
        if v is None:
            return f"N/A({reason})"
        if isinstance(v, (int, float)):
            if not (v is not None and float(v) > 0):
                return f"N/A({reason})"
            return f"{float(v):.2f}"
        s = str(v).strip()
        return s if s else f"N/A({reason})"
    except Exception:
        return f"N/A({reason})"


def _render_pick_strict(it: Dict[str, Any]) -> str:
    sym = it.get("symbol") or "?"
    # chips / bands (strict: never fabricate 0.00)
    tp = it.get("trade_plan") or {}
    bands = tp.get("bands") or {}
    s1 = _fmt_or_na(bands.get("S1"), "missing_key_bands")
    s2 = _fmt_or_na(bands.get("S2"), "missing_key_bands")
    r1 = _fmt_or_na(bands.get("R1"), "missing_key_bands")
    r2 = _fmt_or_na(bands.get("R2"), "missing_key_bands")

    last_close = it.get("last_close")
    last_date = it.get("last_date")
    lc = _fmt_or_na(last_close, "missing_price")
    ld = (str(last_date) if last_date else "N/A(missing_date)")
    parts: List[str] = []
    parts.append(f"标的 {sym}｜收盘价≈{lc}（{ld}）")
    parts.append(f"关键带 S1≈{s1}｜S2≈{s2}｜R1≈{r1}｜R2≈{r2}")
    return "\n".join(parts)


def render_recommendation_narrative(payload: Dict[str, Any]) -> str:
    meta = payload.get("meta") or {}
    ds = payload.get("data_status") or meta.get("data_status") or {}
    snap = ds.get("snapshot") or {}
    ths = payload.get("themes") or meta.get("themes") or []
    picks = payload.get("picks") or []

    lines: List[str] = []
    # provenance visibility
    lines.append("[数据状态]")
    src = snap.get("source") or snap.get("cache_of")
    lines.append(f"- snapshot ok={bool(snap.get('ok'))} source={src or 'N/A'} cache={snap.get('cache') or 'N/A'}")
    if snap.get("error"):
        lines.append(f"- snapshot error={str(snap.get('error'))}")

    # themes with safe parentheses (no empty brackets)
    if ths:
        t_view: List[str] = []
        for t in ths[:3]:
            nm = str((t or {}).get('name') or '?')
            s = str((t or {}).get('strength') or '').strip()
            t_view.append(f"{nm}{('(' + s + ')') if s else ''}")
        lines.append("主题：" + "；".join(t_view))
    else:
        lines.append("主题：N/A(no_themes)")

    # picks block
    if picks:
        for it in picks:
            lines.append(_render_pick_strict(it))
    else:
        lines.append("（无可执行标的）")

    # strict dropped picks disclosure
    dbg = payload.get("debug") or {}
    dp = dbg.get("dropped_picks") or []
    if dp:
        lines.append(f"strict 丢弃 {len(dp)} 个标的（原因见 debug.dropped_picks）")

    return "\n".join(lines)

