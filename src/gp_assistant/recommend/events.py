# 简介：未来事件/日历风险检索（严格模式）。未接入真实数据源，不返回伪造等级。
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List


def _try_import_ak():
    try:
        import akshare as ak  # type: ignore
        return ak
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"akshare 未安装或导入失败: {e}")


def _norm_code(sym: str) -> str:
    s = sym.strip()
    return s


def future_events(symbol: str) -> Dict[str, Any]:
    """Fetch near-term events using akshare (真实来源)。

    包括：
    - 股权登记/除权除息（gbbq）未来15日内事件
    - 限售解禁（若接口可用）未来15日
    无法获取时返回 event_risk=None，并附 missing/error 说明。
    """
    ak = None
    try:
        ak = _try_import_ak()
    except Exception as e:  # noqa: BLE001
        return {"event_risk": None, "evidence": [], "missing": ["akshare"], "error": str(e)}

    sym = _norm_code(symbol)
    now = datetime.now()
    horizon = (now + timedelta(days=15)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")

    evid: List[str] = []
    missing: List[str] = []
    try:
        # 股本变化与分红派息（gbbq）
        df = None
        for argn in ("symbol", "stock"):
            try:
                if argn == "symbol":
                    df = ak.stock_gbbq(symbol=sym)  # type: ignore[attr-defined]
                else:
                    df = ak.stock_gbbq(stock=sym)  # type: ignore[attr-defined]
                break
            except Exception:
                df = None
        if df is not None and len(df) > 0:
            # 兼容不同列名
            date_cols = [c for c in ["除权除息日", "分红实施日", "登记日", "除权日", "发放日"] if c in df.columns]
            if date_cols:
                import pandas as pd
                dser = None
                for c in date_cols:
                    try:
                        dser = pd.to_datetime(df[c], errors="coerce")
                        break
                    except Exception:
                        continue
                if dser is not None:
                    mask = (dser >= pd.to_datetime(today)) & (dser <= pd.to_datetime(horizon))
                    upcoming = df[mask]
                    for _, r in upcoming.head(5).iterrows():
                        typ = r.get("类别") or r.get("事项") or "股本事件"
                        dt = str(r.get(date_cols[0]))
                        evid.append(f"{typ}@{dt}")
        else:
            missing.append("gbbq")
    except Exception as e:  # noqa: BLE001
        missing.append("gbbq")
        evid.append(f"gbbq_error:{e}")

    # 限售解禁（如有接口）：优先 ths 限售解禁接口，若不存在则标记缺失
    try:
        try:
            df_rel = ak.stock_restricted_release_ths()  # type: ignore[attr-defined]
        except Exception:
            df_rel = None
        if df_rel is not None and len(df_rel) > 0:
            import pandas as pd
            # 兼容列名
            code_col = "代码" if "代码" in df_rel.columns else ("code" if "code" in df_rel.columns else None)
            date_col = None
            for c in ("解禁日期", "日期", "date"):
                if c in df_rel.columns:
                    date_col = c
                    break
            if code_col and date_col:
                d = pd.to_datetime(df_rel[date_col], errors="coerce")
                mask = (d >= pd.to_datetime(today)) & (d <= pd.to_datetime(horizon))
                sub = df_rel[mask]
                sub = sub[sub[code_col].astype(str).str.contains(sym)]
                if len(sub) > 0:
                    evid.append(f"解禁事件@{sub.iloc[0][date_col]}")
            else:
                missing.append("restricted_release_cols")
        else:
            missing.append("restricted_release")
    except Exception as e:  # noqa: BLE001
        missing.append("restricted_release")
        evid.append(f"restricted_error:{e}")

    # 风险等级：若未来窗口内存在分红/解禁等事件，风险定为 medium，否则 None
    risk = None
    if evid:
        risk = "medium"
    return {"event_risk": risk, "evidence": evid, "missing": missing}
