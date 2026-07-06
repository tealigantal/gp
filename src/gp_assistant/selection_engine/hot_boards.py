from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping

import pandas as pd

from ..core.paths import store_dir
from .tail_risk import safe_float


_MEM_CACHE: Dict[str, Any] = {"ts": 0.0, "snapshot": None}


def _normalize_code(value: Any) -> str:
    s = str(value or "").strip().lower()
    if "." in s:
        s = s.split(".", 1)[0]
    for prefix in ("sh", "sz", "bj"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else ""


def _pick_col(df: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    normalized = {str(col).strip().lower(): str(col) for col in df.columns}
    for cand in candidates:
        key = str(cand).strip().lower()
        if key in normalized:
            return normalized[key]
    return None


def _numeric(df: pd.DataFrame, col: str | None) -> pd.Series:
    if not col or col not in df.columns:
        return pd.Series(dtype="float64")
    src = df[col]
    try:
        if src.dtype == object:
            src = src.astype(str).str.replace("%", "", regex=False).str.replace(",", "", regex=False)
        return pd.to_numeric(src, errors="coerce")
    except Exception:
        return pd.to_numeric(df[col], errors="coerce")


def _board_score(row: Mapping[str, Any]) -> float:
    pct = safe_float(row.get("pct_chg")) or 0.0
    turnover = safe_float(row.get("turnover_rate")) or 0.0
    leader = safe_float(row.get("leader_pct_chg")) or 0.0
    up_count = safe_float(row.get("up_count"))
    down_count = safe_float(row.get("down_count"))
    breadth = 0.5
    if up_count is not None and down_count is not None and (up_count + down_count) > 0:
        breadth = up_count / (up_count + down_count)
    score = (
        0.45 * max(0.0, min(1.0, pct / 6.0))
        + 0.25 * max(0.0, min(1.0, breadth))
        + 0.15 * max(0.0, min(1.0, turnover / 8.0))
        + 0.15 * max(0.0, min(1.0, leader / 10.0))
    )
    return float(max(0.0, min(1.0, score)))


def _normalize_board_df(df: pd.DataFrame, *, board_type: str, topn: int) -> List[Dict[str, Any]]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []
    x = df.copy()
    name_col = _pick_col(x, ["板块名称", "名称", "name", "行业名称", "概念名称"])
    code_col = _pick_col(x, ["板块代码", "代码", "code"])
    pct_col = _pick_col(x, ["涨跌幅", "涨幅", "pct_chg", "涨跌幅(%)"])
    turnover_col = _pick_col(x, ["换手率", "换手率%", "turnover_rate"])
    up_col = _pick_col(x, ["上涨家数", "上涨数", "up_count"])
    down_col = _pick_col(x, ["下跌家数", "下跌数", "down_count"])
    leader_col = _pick_col(x, ["领涨股票", "领涨股", "leader"])
    leader_pct_col = _pick_col(x, ["领涨股票-涨跌幅", "领涨股涨跌幅", "leader_pct_chg"])
    if name_col is None or pct_col is None:
        return []
    pct = _numeric(x, pct_col)
    x = x.assign(_pct=pct).sort_values("_pct", ascending=False).head(max(1, topn))
    out: List[Dict[str, Any]] = []
    for idx, row in x.iterrows():
        item = {
            "type": board_type,
            "name": str(row.get(name_col) or "").strip(),
            "code": str(row.get(code_col) or "").strip() if code_col else None,
            "pct_chg": safe_float(row.get(pct_col)),
            "turnover_rate": safe_float(row.get(turnover_col)) if turnover_col else None,
            "up_count": safe_float(row.get(up_col)) if up_col else None,
            "down_count": safe_float(row.get(down_col)) if down_col else None,
            "leader": str(row.get(leader_col) or "").strip() if leader_col else None,
            "leader_pct_chg": safe_float(row.get(leader_pct_col)) if leader_pct_col else None,
        }
        if item["name"]:
            item["score"] = _board_score(item)
            out.append(item)
    return out


def _normalize_members(df: pd.DataFrame) -> List[str]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []
    code_col = _pick_col(df, ["代码", "code", "symbol", "股票代码"])
    if code_col is None:
        return []
    out: List[str] = []
    for value in df[code_col].tolist():
        code = _normalize_code(value)
        if code:
            out.append(code)
    return sorted(set(out))


def _default_fetcher(route: str, symbol: str | None = None) -> pd.DataFrame:
    import akshare as ak  # type: ignore

    if route == "industry_name":
        return ak.stock_board_industry_name_em()
    if route == "concept_name":
        return ak.stock_board_concept_name_em()
    if route == "industry_cons":
        return ak.stock_board_industry_cons_em(symbol=str(symbol or ""))
    if route == "concept_cons":
        return ak.stock_board_concept_cons_em(symbol=str(symbol or ""))
    raise ValueError(f"unknown hot board route: {route}")


def build_hot_board_snapshot(
    *,
    enabled: bool = True,
    topn: int = 5,
    ttl_sec: int = 600,
    fetcher: Callable[[str, str | None], pd.DataFrame] | None = None,
) -> Dict[str, Any]:
    if not enabled:
        return {"status": "skipped", "reason": "disabled", "boards": [], "memberships": {}, "attempted": []}

    now = time.time()
    cached = _MEM_CACHE.get("snapshot")
    if cached is not None and (now - float(_MEM_CACHE.get("ts") or 0.0)) <= max(1, ttl_sec):
        out = dict(cached)
        out["status"] = "cached"
        return out

    fetch = fetcher or _default_fetcher
    attempted: List[str] = []
    try:
        attempted.append("industry_name")
        industry_df = fetch("industry_name", None)
        attempted.append("concept_name")
        concept_df = fetch("concept_name", None)
        boards = _normalize_board_df(industry_df, board_type="industry", topn=topn)
        boards.extend(_normalize_board_df(concept_df, board_type="concept", topn=topn))
        memberships: Dict[str, List[Dict[str, Any]]] = {}
        member_errors: List[str] = []
        for board in boards:
            route = "industry_cons" if board.get("type") == "industry" else "concept_cons"
            key = str(board.get("name") or board.get("code") or "")
            attempted.append(f"{route}:{key}")
            try:
                cons = fetch(route, key)
                members = _normalize_members(cons)
                board["member_count"] = len(members)
                for code in members:
                    memberships.setdefault(code, []).append(
                        {
                            "type": board.get("type"),
                            "name": board.get("name"),
                            "pct_chg": board.get("pct_chg"),
                            "score": board.get("score"),
                        }
                    )
            except Exception as ex:  # noqa: BLE001
                member_errors.append(f"{route}:{key}:{type(ex).__name__}: {ex}")
        snapshot = {
            "status": "available",
            "reason": None,
            "boards": boards,
            "memberships": memberships,
            "attempted": attempted,
            "error": None,
            "member_errors": member_errors[:5],
            "as_of_ts": now,
        }
        _MEM_CACHE.update({"ts": now, "snapshot": snapshot})
        try:
            path = store_dir() / "cache" / "hot_boards" / "latest.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return snapshot
    except Exception as ex:  # noqa: BLE001
        return {
            "status": "unavailable",
            "reason": "fetch_failed",
            "boards": [],
            "memberships": {},
            "attempted": attempted,
            "error": f"{type(ex).__name__}: {ex}",
        }


def score_symbols_for_hot_boards(symbols: Iterable[str], snapshot: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    status = str(snapshot.get("status") or "")
    syms = [_normalize_code(s) for s in symbols]
    if status not in {"available", "cached"}:
        return {sym: {"score": 0.0, "reason_codes": ["hot_board_unavailable"], "boards": []} for sym in syms if sym}
    memberships = snapshot.get("memberships") if isinstance(snapshot, Mapping) else {}
    member_map = memberships if isinstance(memberships, Mapping) else {}
    out: Dict[str, Dict[str, Any]] = {}
    for sym in syms:
        if not sym:
            continue
        boards = list(member_map.get(sym) or [])
        if not boards:
            out[sym] = {"score": 0.0, "reason_codes": ["hot_board_no_match"], "boards": []}
            continue
        score = max(safe_float(board.get("score")) or 0.0 for board in boards)
        out[sym] = {
            "score": float(max(0.0, min(1.0, score))),
            "reason_codes": ["hot_board_match"],
            "boards": boards[:3],
        }
    return out


def summarize_hot_board_snapshot(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    boards = snapshot.get("boards") if isinstance(snapshot, Mapping) else []
    return {
        "status": snapshot.get("status"),
        "reason": snapshot.get("reason"),
        "error": snapshot.get("error"),
        "attempted": list(snapshot.get("attempted") or [])[:20],
        "boards": list(boards or [])[:10],
        "as_of_ts": snapshot.get("as_of_ts"),
    }
