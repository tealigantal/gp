from __future__ import annotations

from typing import Any, Dict, List, Optional

import os
import time
import json
import pandas as pd

from ..core.paths import store_dir


_CACHE: Dict[str, Any] = {"ts": 0.0, "themes": None, "source": None}
_LAST_STATUS: Dict[str, Any] = {"attempted": [], "error": None, "ts": 0.0}


def _ttl() -> int:
    try:
        return int(os.getenv("GP_THEME_CONCEPT_TTL_SEC", "60"))
    except Exception:
        return 60


def last_concept_status() -> Dict[str, Any]:
    return dict(_LAST_STATUS)


def _detect_rank_col(df: pd.DataFrame) -> Optional[str]:
    candidates = ["涨跌幅", "涨跌幅(%)", "涨跌", "changePct", "pct_chg"]
    cols = set(map(str, df.columns))
    for c in candidates:
        if c in cols:
            return c
    return None


def _normalize_strength(v: Any) -> str:
    try:
        s = pd.to_numeric(str(v).strip().rstrip("% ").replace(",", ""), errors="coerce")
        if pd.isna(s):
            return ""
        return f"{float(s):.2f}%"
    except Exception:
        return ""


def _build_from_board_df(df: pd.DataFrame, *, board_type: str, topn: int, source: str) -> List[Dict[str, Any]]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []
    rank_col = _detect_rank_col(df)
    if not rank_col:
        return []
    x = df.copy()
    try:
        x["_r"] = pd.to_numeric(x[rank_col].astype(str).str.rstrip("% "), errors="coerce")
    except Exception:
        x["_r"] = pd.to_numeric(x[rank_col], errors="coerce")
    x_valid = x.dropna(subset=["_r"]).copy()
    if x_valid.empty:
        return []
    x = x_valid.sort_values("_r", ascending=False)
    name_col = "板块名称" if "板块名称" in x.columns else ("名称" if "名称" in x.columns else str(list(x.columns)[0]))
    code_col = "板块代码" if "板块代码" in x.columns else ("代码" if "代码" in x.columns else None)
    leader_col = None
    for c in ["领涨股", "领涨股票", "龙头股", "领涨-股票"]:
        if c in x.columns:
            leader_col = c
            break
    leader_chg_col = None
    for c in ["领涨股-涨跌幅", "领涨-涨跌幅", "领涨股涨跌幅"]:
        if c in x.columns:
            leader_chg_col = c
            break
    out: List[Dict[str, Any]] = []
    prefix = "行业-" if board_type == "industry" else "概念-"
    for _, r in x.head(max(0, int(topn))).iterrows():
        evidence: Dict[str, Any] = {}
        if code_col:
            evidence["board_code"] = str(r.get(code_col))
        if leader_col:
            evidence["leader_stock"] = str(r.get(leader_col))
        if leader_chg_col:
            evidence["leader_stock_chg"] = _normalize_strength(r.get(leader_chg_col))
        out.append({
            "name": f"{prefix}{str(r.get(name_col))}",
            "strength": _normalize_strength(r.get(rank_col)),
            "evidence": evidence,
            "source": source,
        })
    return out


def build_concept_themes(topn: int = 2, reason: Optional[str] = None) -> List[Dict[str, Any]]:
    """Build themes via EM industry + concept name endpoints.

    - Use ak.stock_board_industry_name_em() and ak.stock_board_concept_name_em()
    - Limit to topn for each type
    - Do NOT call spot endpoints without symbol
    - Optional enrichment: top 1 for each fetch constituents and attach leaders
    """
    now = time.time()
    _LAST_STATUS.update({"attempted": [], "error": None, "ts": now})
    try:
        if (_CACHE.get("themes") is not None) and (now - float(_CACHE.get("ts", 0.0)) <= _ttl()):
            return list(_CACHE.get("themes") or [])
    except Exception:
        pass
    try:
        import akshare as ak  # type: ignore
    except Exception as e:  # noqa: BLE001
        _LAST_STATUS.update({"error": f"akshare_import_failed: {e}"})
        # try disk cache when import fails
        cache_p = store_dir() / "cache" / "theme_concept_themes.json"
        try:
            if cache_p.exists():
                obj = json.loads(cache_p.read_text(encoding="utf-8"))
                max_stale = int(os.getenv("GP_THEME_CONCEPT_MAX_STALE_SEC", "86400"))
                if time.time() - float(obj.get("ts", 0.0)) <= max_stale:
                    _LAST_STATUS["attempted"].append("disk_cache")
                    _LAST_STATUS["error"] = f"stale_cache_used;{_LAST_STATUS.get('error')}"
                    return list(obj.get("themes") or [])
        except Exception:
            pass
        return []

    themes: List[Dict[str, Any]] = []
    errors: List[str] = []
    try:
        _LAST_STATUS["attempted"].append("industry_name_em")
        df_ind = ak.stock_board_industry_name_em()  # type: ignore[attr-defined]
        themes += _build_from_board_df(df_ind, board_type="industry", topn=topn, source="akshare:industry_name_em")
    except Exception as e:  # noqa: BLE001
        errors.append(f"industry_name_em:{e}")
        # THS fallback if available
        try:
            if hasattr(ak, "stock_board_industry_name_ths"):
                _LAST_STATUS["attempted"].append("industry_name_ths")
                df_ind2 = ak.stock_board_industry_name_ths()  # type: ignore[attr-defined]
                themes += _build_from_board_df(df_ind2, board_type="industry", topn=topn, source="akshare:industry_name_ths")
        except Exception as e2:  # noqa: BLE001
            errors.append(f"industry_name_ths:{e2}")
    try:
        _LAST_STATUS["attempted"].append("concept_name_em")
        df_con = ak.stock_board_concept_name_em()  # type: ignore[attr-defined]
        themes += _build_from_board_df(df_con, board_type="concept", topn=topn, source="akshare:concept_name_em")
    except Exception as e:  # noqa: BLE001
        errors.append(f"concept_name_em:{e}")
        # THS fallback if available
        try:
            if hasattr(ak, "stock_board_concept_name_ths"):
                _LAST_STATUS["attempted"].append("concept_name_ths")
                df_con2 = ak.stock_board_concept_name_ths()  # type: ignore[attr-defined]
                themes += _build_from_board_df(df_con2, board_type="concept", topn=topn, source="akshare:concept_name_ths")
        except Exception as e2:  # noqa: BLE001
            errors.append(f"concept_name_ths:{e2}")

    # Optional enrichment for top 1 of each type (fast, TTL cache on disk)
    try:
        if themes:
            def _first_of(prefix: str):
                for t in themes:
                    if isinstance(t, dict) and str(t.get("name", "")).startswith(prefix):
                        return t
                return None
            ind = _first_of("行业-")
            con = _first_of("概念-")
            cache_root = store_dir() / "cache" / "theme_cons"
            cache_root.mkdir(parents=True, exist_ok=True)
            if ind and isinstance(ind.get("evidence"), dict) and ind["evidence"].get("board_code"):
                key = f"industry_{ind['evidence']['board_code']}.json"
                p = cache_root / key
                data = None
                if p.exists():
                    try:
                        data = json.loads(p.read_text(encoding="utf-8"))
                    except Exception:
                        data = None
                if (not data) or (now - float(data.get("ts", 0.0)) > _ttl()):
                    try:
                        cons = ak.stock_board_industry_cons_em(symbol=str(ind["evidence"]["board_code"]))  # type: ignore[attr-defined]
                        if isinstance(cons, pd.DataFrame) and not cons.empty:
                            rc = cons.copy()
                            rank_col = _detect_rank_col(rc) or "涨跌幅"
                            try:
                                rc["_r"] = pd.to_numeric(rc[rank_col].astype(str).str.rstrip("% "), errors="coerce")
                            except Exception:
                                rc["_r"] = pd.to_numeric(rc.get(rank_col), errors="coerce")
                            rc = rc.dropna(subset=["_r"]).sort_values("_r", ascending=False).head(5)
                            leaders = []
                            code_c = "代码" if "代码" in rc.columns else ("code" if "code" in rc.columns else None)
                            name_c = "名称" if "名称" in rc.columns else ("name" if "name" in rc.columns else None)
                            for _, rr in rc.iterrows():
                                leaders.append({"code": str(rr.get(code_c)) if code_c else None, "name": str(rr.get(name_c)) if name_c else None, "pct_chg": _normalize_strength(rr.get(rank_col))})
                            data = {"ts": now, "leaders": leaders}
                            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                if data and data.get("leaders"):
                    ind.setdefault("evidence", {})["leaders"] = data.get("leaders")
            if con and isinstance(con.get("evidence"), dict) and con["evidence"].get("board_code"):
                key = f"concept_{con['evidence']['board_code']}.json"
                p = cache_root / key
                data = None
                if p.exists():
                    try:
                        data = json.loads(p.read_text(encoding="utf-8"))
                    except Exception:
                        data = None
                if (not data) or (now - float(data.get("ts", 0.0)) > _ttl()):
                    try:
                        cons = ak.stock_board_concept_cons_em(symbol=str(con["evidence"]["board_code"]))  # type: ignore[attr-defined]
                        if isinstance(cons, pd.DataFrame) and not cons.empty:
                            rc = cons.copy()
                            rank_col = _detect_rank_col(rc) or "涨跌幅"
                            try:
                                rc["_r"] = pd.to_numeric(rc[rank_col].astype(str).str.rstrip("% "), errors="coerce")
                            except Exception:
                                rc["_r"] = pd.to_numeric(rc.get(rank_col), errors="coerce")
                            rc = rc.dropna(subset=["_r"]).sort_values("_r", ascending=False).head(5)
                            leaders = []
                            code_c = "代码" if "代码" in rc.columns else ("code" if "code" in rc.columns else None)
                            name_c = "名称" if "名称" in rc.columns else ("name" if "name" in rc.columns else None)
                            for _, rr in rc.iterrows():
                                leaders.append({"code": str(rr.get(code_c)) if code_c else None, "name": str(rr.get(name_c)) if name_c else None, "pct_chg": _normalize_strength(rr.get(rank_col))})
                            data = {"ts": now, "leaders": leaders}
                            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                if data and data.get("leaders"):
                    con.setdefault("evidence", {})["leaders"] = data.get("leaders")
    except Exception:
        pass

    if themes:
        _CACHE.update({"ts": now, "themes": themes, "source": "em_or_ths:name"})
        _LAST_STATUS.update({"error": None})
        # persist disk cache (final themes only)
        try:
            p = store_dir() / "cache" / "theme_concept_themes.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"ts": now, "themes": themes, "source": _CACHE.get("source")}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return themes
    if errors:
        _LAST_STATUS.update({"error": ";".join(errors)})
    # final: try disk cache when we failed to build anything
    try:
        cache_p = store_dir() / "cache" / "theme_concept_themes.json"
        if cache_p.exists():
            obj = json.loads(cache_p.read_text(encoding="utf-8"))
            max_stale = int(os.getenv("GP_THEME_CONCEPT_MAX_STALE_SEC", "86400"))
            if time.time() - float(obj.get("ts", 0.0)) <= max_stale:
                _LAST_STATUS["attempted"].append("disk_cache")
                _LAST_STATUS["error"] = f"stale_cache_used;{_LAST_STATUS.get('error')}"
                return list(obj.get("themes") or [])
    except Exception:
        pass
    return []
