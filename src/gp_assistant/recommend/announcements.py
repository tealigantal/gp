# 简介：公告风险检索（占位/轻实现）。提供公告风险等级与简短证据，
# 用于交易计划中的风险提示。
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from ..core.paths import store_dir


def _cache_path(symbol: str) -> str:
    return str(store_dir() / "cache" / "ann" / f"{symbol}.json")


def _load_cache(symbol: str) -> Optional[Dict[str, Any]]:
    p = _cache_path(symbol)
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(symbol: str, data: Dict[str, Any]) -> None:
    p = store_dir() / "cache" / "ann"
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{symbol}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def fetch_announcements(symbol: str) -> Dict[str, Any]:
    # Try cache first
    cached = _load_cache(symbol)
    if cached:
        return {**cached, "source": "cache"}
    # Try CNINFO API (may fail due to network)
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    result = {"list": [], "risk_level": "medium", "evidence": [], "catalyst": [], "_reason": None}
    try:
        # CNINFO requires complex params; use a placeholder endpoint that's public. If fails, degrade.
        # For compliance we attempt and record failure without crashing.
        url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
        params = {"plate": "sz;sh", "seDate": f"{start}~{end}", "searchkey": symbol, "pageNum": 1, "pageSize": 30}
        r = requests.post(url, data=params, timeout=10)
        r.raise_for_status()
        js = r.json()
        items = js.get("announcements", []) if isinstance(js, dict) else []
        out_items: List[Dict[str, Any]] = []
        for it in items[:20]:
            out_items.append({
                "title": it.get("announcementTitle", ""),
                "date": it.get("announcementTime", ""),
                "type": it.get("announcementType", ""),
                "url": it.get("adjunctUrl", ""),
                "source": "cninfo",
            })
        result["list"] = out_items
        # risk keywords
        text = "\n".join(x.get("title", "") for x in out_items)
        risk_kw = ["减持", "解禁", "异常波动", "风险提示", "问询", "立案", "下修", "预亏", "失败"]
        hits = [kw for kw in risk_kw if kw in text]
        if any(hits):
            result["risk_level"] = "high" if len(hits) >= 2 else "medium"
            result["evidence"] = hits[:2]
        else:
            result["risk_level"] = "low"
        result["_reason"] = "cninfo_ok"
    except Exception as e:  # noqa: BLE001
        result["_reason"] = f"cninfo_failed:{e}"
        # Degrade risk upwards, no crash
        result["risk_level"] = "medium"
    _save_cache(symbol, result)
    return result
