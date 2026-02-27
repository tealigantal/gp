from __future__ import annotations

from typing import Any, Dict, List, Optional

import time
from datetime import datetime, timezone

import pandas as pd


def _iso_now() -> str:
    try:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    except Exception:
        return str(datetime.now())


def _detect_col(cols: List[str], keywords: List[str]) -> Optional[str]:
    s = [str(c) for c in cols]
    for kw in keywords:
        for c in s:
            if kw in str(c):
                return c
    return None


def build_mainline(indicator: str = "今日", topn: int = 3) -> Dict[str, Any]:
    """Build mainline/主线 via AkShare sector fund flow rank.

    Tries both 行业资金流 and 概念资金流, selects topn by 主力净流入-净额.
    """
    try:
        import akshare as ak  # type: ignore
    except Exception as e:  # noqa: BLE001
        return {"indicator": indicator, "sectors": [], "as_of_ts": _iso_now(), "errors": [f"akshare_import_failed:{e}"]}

    out_sectors: List[Dict[str, Any]] = []
    errors: List[str] = []
    for sector_type in ["行业资金流", "概念资金流"]:
        try:
            df = ak.stock_sector_fund_flow_rank(indicator=indicator, sector_type=sector_type)  # type: ignore[attr-defined]
            if isinstance(df, pd.DataFrame) and not df.empty:
                x = df.copy()
                cols = [str(c) for c in x.columns]
                chg_col = None
                for cand in ["涨跌幅", "涨跌幅(%)", "涨跌"]:
                    if cand in cols:
                        chg_col = cand
                        break
                inflow_col = None
                for cand in ["主力净流入-净额", "主力净流入净额", "主力净流入净额(亿)"]:
                    if cand in cols or any(cand in c for c in cols):
                        inflow_col = _detect_col(cols, [cand])
                        break
                inflow_pct_col = _detect_col(cols, ["主力净流入-净占比", "主力净流入净占比"])
                name_col = "名称" if "名称" in cols else ("板块名称" if "板块名称" in cols else str(cols[0]))
                if inflow_col is None:
                    inflow_col = name_col  # fallback to avoid crash; sorted won't work
                try:
                    x["_inflow"] = pd.to_numeric(x[inflow_col].astype(str).str.replace(",", ""), errors="coerce")
                except Exception:
                    x["_inflow"] = pd.to_numeric(x.get(inflow_col), errors="coerce")
                x = x.sort_values("_inflow", ascending=False)
                for _, r in x.head(max(0, int(topn))).iterrows():
                    item = {
                        "sector_type": sector_type,
                        "name": str(r.get(name_col)),
                        "pct_chg": None if chg_col is None else str(r.get(chg_col)),
                        "main_inflow": None if inflow_col is None else str(r.get(inflow_col)),
                        "main_inflow_pct": None if inflow_pct_col is None else str(r.get(inflow_pct_col)),
                        "leader_stock": r.get("领涨股") if "领涨股" in cols else None,
                        "source": "akshare:stock_sector_fund_flow_rank",
                        "indicator": indicator,
                    }
                    out_sectors.append(item)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sector_type}:{e}")
            continue

    return {"indicator": indicator, "sectors": out_sectors, "as_of_ts": _iso_now(), "errors": errors}

