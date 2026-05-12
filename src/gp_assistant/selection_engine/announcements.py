# 简介：公告风险检索（严格模式）。尝试 CNINFO；失败不降级，不造数据，返回 risk_level=None 并附 error。
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from ..core.paths import store_dir
from ..core.config import load_config
from ..llm.semantics import assess_announcement_risk
from ..search.history_store import (
    canonical_query_id,
    ensure_query,
    compute_next_range,
    upsert_items,
    list_items,
)


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
    """Fetch company announcements with incremental history-store.

    - Uses history_store keyed by {kind:'ann', symbol, provider:'cninfo'}
    - On each call, incrementally fetch [watermark-2d, now] and upsert
    - Returns last 30d merged from local store with simple risk summary
    """
    cfg = load_config()
    now = datetime.now(tz=timezone.utc)
    end_iso = now.date().isoformat()
    lookback_days = 30
    default_start_iso = (now - timedelta(days=lookback_days)).date().isoformat()

    # History-store setup
    qparams = {"kind": "ann", "symbol": str(symbol), "provider": "cninfo"}
    qid = canonical_query_id(qparams)
    ensure_query(qid, qparams)

    # Compute incremental window with safety lookback
    start_iso, end_iso_eff = compute_next_range(qid, user_start=default_start_iso, user_end=end_iso, safety_lookback_days=2)
    start_iso = start_iso or default_start_iso
    end_iso_eff = end_iso_eff or end_iso

    # Try CNINFO network fetch for the incremental window
    net_ok = False
    try:
        url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
        params = {
            "plate": "sz;sh",
            "seDate": f"{start_iso}~{end_iso_eff}",
            "searchkey": symbol,
            "pageNum": 1,
            "pageSize": 60,
        }
        r = requests.post(url, data=params, timeout=10)
        r.raise_for_status()
        js = r.json()
        items = js.get("announcements", []) if isinstance(js, dict) else []

        def _iid(it: Dict[str, Any]) -> str:
            base = str(it.get("id") or it.get("adjunctUrl") or (str(it.get("announcementTitle", "")) + "|" + str(it.get("announcementTime", ""))))
            # keep short id; stability is sufficient
            import hashlib
            return hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]

        parsed: List[Dict[str, Any]] = []
        for it in items:
            d = str(it.get("announcementTime") or "").strip()
            # Convert to YYYY-MM-DD if timestamp-like
            try:
                if d.isdigit():
                    # milliseconds
                    ts = int(d)
                    if ts > 10_000_000_000:
                        ts = ts // 1000
                    d_iso = datetime.utcfromtimestamp(ts).date().isoformat()
                else:
                    d_iso = datetime.fromisoformat(d.replace("/", "-")[:10]).date().isoformat()
            except Exception:
                d_iso = default_start_iso
            parsed.append({
                "id": _iid(it),
                "date": d_iso,
                "title": it.get("announcementTitle", ""),
                "type": it.get("announcementType", ""),
                "url": it.get("adjunctUrl", ""),
                "source": "cninfo",
            })
        if parsed:
            upsert_items(qid, parsed, id_key="id", time_key="date", etag_key=None)
        net_ok = True
    except Exception as e:  # noqa: BLE001
        # best effort; fall through to local store
        net_err = str(e)

    # Read last 30d from store and summarize
    since_iso = default_start_iso
    rows = list_items(qid, since=since_iso)
    lst = [r["payload"] for r in rows]
    semantic_error = None
    try:
        risk = assess_announcement_risk(lst)
        risk_level = risk.risk_level
        evidence = risk.evidence
        semantic_reason = risk.reason
    except Exception as e:  # noqa: BLE001
        risk_level = None
        evidence = []
        semantic_reason = None
        semantic_error = str(e)

    result: Dict[str, Any] = {
        "list": lst,
        "risk_level": risk_level,
        "evidence": evidence,
        "catalyst": [],
        "_reason": "cninfo_ok" if net_ok else "cninfo_cached_or_failed",
        "source": "store:cninfo",
    }
    if semantic_reason:
        result["risk_reason"] = semantic_reason
    if semantic_error:
        result["semantic_error"] = semantic_error
    if not net_ok:
        result["error"] = locals().get("net_err")
    return result
