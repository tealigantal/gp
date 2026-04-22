from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _fmt_num(value: Any) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if num == 0.0:
        return "N/A"
    return f"{num:.2f}"


def _render_themes(themes: Iterable[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for theme in themes or []:
        name = str((theme or {}).get("name") or "").strip()
        if not name:
            continue
        strength = str((theme or {}).get("strength") or "").strip()
        parts.append(f"{name}({strength})" if strength else name)
    return ", ".join(parts) if parts else "N/A"


def render_recommendation(payload: Dict[str, Any]) -> str:
    themes = _render_themes(payload.get("themes") or [])
    picks = payload.get("picks") or []
    env = (payload.get("env") or {}).get("grade") or "N/A"
    return f"env: {env}\nthemes: {themes}\npicks: {len(picks)}"


def render_recommendation_narrative(payload: Dict[str, Any]) -> str:
    lines: List[str] = [render_recommendation(payload)]
    for idx, pick in enumerate(payload.get("picks") or [], start=1):
        trade_plan = (pick or {}).get("trade_plan") or {}
        bands = trade_plan.get("bands") or {}
        symbol = str((pick or {}).get("symbol") or f"pick-{idx}")
        lines.append(
            f"{idx}. {symbol} last_close={_fmt_num((pick or {}).get('last_close'))} "
            f"S1={_fmt_num(bands.get('S1'))} R1={_fmt_num(bands.get('R1'))}"
        )
    dropped = ((payload.get("debug") or {}).get("dropped_picks") or [])
    if dropped:
        reasons = ", ".join(
            f"{item.get('symbol')}: {item.get('reason')}" for item in dropped if isinstance(item, dict)
        )
        lines.append(f"strict dropped: {reasons or 'N/A'}")
    snapshot = ((payload.get("data_status") or {}).get("snapshot") or {})
    lines.append(
        "snapshot: "
        f"ok={snapshot.get('ok')} source={snapshot.get('source') or 'N/A'} cache={snapshot.get('cache') or 'N/A'}"
    )
    return "\n".join(lines)
