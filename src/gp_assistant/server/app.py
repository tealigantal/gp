# src/gp_assistant/server/app.py
"""
FastAPI application for gp_assistant.

Routes:
- Legacy (kept for compatibility): /chat, /recommend, /health
- New API (for SPA): /api/chat, /api/recommend, /api/health
- Helpers:
  - GET /api/ohlcv/{symbol}
  - GET /api/recommend/{date}  (read store/recommend/{date}.json)
  - GET /api/recommend/modes   (list available recommend modes)

Also adds optional CORS support controlled by env GP_CORS_ORIGINS.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..chat import event_store
from ..chat.orchestrator import handle_message
from ..core.config import load_config
from ..core.errors import APIError
from ..core.paths import store_dir, results_dir
from ..dev.fixtures import dev_ohlcv_bars
from ..recommend.compact_payload import compact_recommend_payload
from ..recommend.runner import list_modes as recommend_list_modes
from ..kernel.facade import (
    get_artifact_v2 as kernel_get_artifact_v2,
    compare_symbols as kernel_compare_symbols,
    get_pick_detail as kernel_pick_detail,
    get_strategy_validation as kernel_strategy_validation,
    get_paperfolio as kernel_get_paperfolio,
)
from .models import (
    ChatReq,
    ChatResp,
    EventOut,
    HealthResp,
    OHLCVBar,
    OHLCVResp,
    RecommendReq,
    RecommendResp,
    CompareReq,
    CompareResp,
    PickDetailReq,
    PickDetailResp,
    RecommendV2Resp,
    SyncReq,
    SyncResp,
    StrategyValidationResp,
    PaperfolioResp,
    LiveShadowResp,
    ValidationSummaryResp,
    PortfolioResp,
    WorkbenchResp,
    OperatorIntentActionReq,
    OperatorIntentActionResp,
)

app = FastAPI(title="gp_assistant", version="1.1.0")


def _maybe_enable_cors(application: FastAPI) -> None:
    origins_var = os.getenv("GP_CORS_ORIGINS", "").strip()
    if not origins_var:
        return
    origins = [o.strip() for o in origins_var.split(",") if o.strip()]
    if not origins:
        return
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


_maybe_enable_cors(app)


@app.exception_handler(APIError)
async def api_error_handler(_, exc: APIError):  # noqa: ANN001
    return JSONResponse(status_code=exc.status_code, content=exc.to_json())


def _compact_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Delegate to shared helper to keep orchestrator/app consistent
    return compact_recommend_payload(payload)


def _handle_chat(req: ChatReq) -> ChatResp:
    data = handle_message(req.session_id, req.message, getattr(req, "message_id", None))
    ctx = data.get("followup_context") or {}
    return ChatResp(
        session_id=data.get("session_id"),
        reply=str(data.get("reply", "")),
        tool_trace=data.get("tool_trace", {}),
        assistant_message_id=data.get("assistant_message_id"),
        agent_trace=data.get("agent_trace"),
        resolved_symbol=data.get("resolved_symbol"),
        degraded=data.get("degraded"),
        degrade_reason=data.get("degrade_reason"),
        followup_context=ctx,
        run_id=ctx.get("active_run_id"),
        symbols=(ctx.get("active_symbols") if isinstance(ctx.get("active_symbols"), list) else None),
        fallback_used=bool(data.get("degraded") is True),
    )


def _handle_recommend(req: RecommendReq) -> Dict[str, Any]:
    # IMPORTANT: use runner (multi-mode)
    from ..recommend.runner import run as recommend_run  # lazy import
    result = recommend_run(
        mode=req.mode,
        date=req.date,
        topk=req.topk or 3,
        universe=req.universe or "auto",
        symbols=req.symbols,
        risk_profile=req.risk_profile or "normal",
    )

    detail = (req.detail or "compact").lower()
    if detail not in {"compact", "full"}:
        detail = "compact"

    if detail == "compact":
        return _compact_payload(result)

    return result


def _service_health_status() -> Dict[str, Any]:
    """Collect minimal service health without external dependencies."""
    latest_ok = False
    latest_as_of: Optional[str] = None
    latest_as_of_ts: Optional[str] = None
    latest_stage: Optional[str] = None
    shadow_metrics_ok = False
    last_error: Optional[str] = None

    try:
        p = store_dir() / "recommend" / "latest.json"
        if p.exists():
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
                # minimal schema checks
                if isinstance(obj, dict) and isinstance(obj.get("picks"), list):
                    latest_ok = True
                latest_as_of = str(obj.get("as_of")) if obj.get("as_of") is not None else None
                latest_as_of_ts = str(obj.get("as_of_ts")) if obj.get("as_of_ts") is not None else None
                latest_stage = str(obj.get("stage")) if obj.get("stage") is not None else None
                # try locate live_shadow metrics by date
                date_part = None
                s = latest_as_of or ""
                if len(s) == 8 and s.isdigit():
                    date_part = s
                else:
                    # attempt to parse from as_of_ts like YYYYMMDD HH:MM:SS or YYYY-MM-DD
                    t = latest_as_of_ts or s
                    if isinstance(t, str):
                        t2 = t.replace("-", "")
                        if len(t2) >= 8 and t2[:8].isdigit():
                            date_part = t2[:8]
                if date_part:
                    metrics = results_dir() / "live_shadow" / date_part / "metrics.json"
                    shadow_metrics_ok = metrics.exists()
            except Exception as e:  # noqa: BLE001
                last_error = f"latest_read_error: {e}"
        else:
            last_error = "latest_missing"
    except Exception as e:  # noqa: BLE001
        last_error = f"service_health_error: {e}"

    return {
        "latest_ok": bool(latest_ok),
        "latest_as_of": latest_as_of,
        "latest_as_of_ts": latest_as_of_ts,
        "stage": latest_stage,
        "shadow_metrics_ok": bool(shadow_metrics_ok),
        "last_error": last_error,
    }


def _health_live() -> Dict[str, Any]:
    """Extremely lightweight liveness: process responds and config parses minimally."""
    now = datetime.now().isoformat()
    status = {
        "ok": True,
        "status": "live",
        "service": "gp-assistant",
        "ts": now,
    }
    return status


def _check_store_rw() -> Dict[str, Any]:
    try:
        base = store_dir()
        base.mkdir(parents=True, exist_ok=True)
        p = base / ".probe"
        p.write_text("ok", encoding="utf-8")
        try:
            p.unlink(missing_ok=True)  # type: ignore[arg-type]
        except TypeError:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        return {"ok": True, "path": str(base)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _check_config() -> Dict[str, Any]:
    try:
        cfg = load_config()
        return {"ok": True, "run_mode": cfg.run_mode, "dev_mode": cfg.dev_mode}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _llm_proxy_health_url() -> Optional[str]:
    base = os.getenv("LLM_BASE_URL", "").strip()
    if not base:
        return None
    # typical: http://llm-proxy:8080/v1 -> http://llm-proxy:8080/health
    if base.endswith("/v1"):
        return base[:-3] + "health"
    # else try appending /health
    if base.endswith("/"):
        return base + "health"
    return base + "/health"


def _check_llm_proxy(timeout: float = 0.8) -> Dict[str, Any]:
    url = _llm_proxy_health_url()
    if not url:
        return {"ok": False, "skipped": True, "reason": "LLM_BASE_URL_missing"}
    try:
        import urllib.request  # noqa: PLC0415

        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            code = int(getattr(resp, "status", 0) or 0)
            return {"ok": (200 <= code < 500), "status": code, "url": url}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "url": url}


def _health_ready() -> Dict[str, Any]:
    now = datetime.now().isoformat()
    checks = {
        "store": _check_store_rw(),
        "config": _check_config(),
        "llm_proxy": _check_llm_proxy(),
    }
    ok = all(v.get("ok") for v in checks.values())
    return {
        "ok": bool(ok),
        "status": "ready" if ok else "degraded",
        "service": "gp-assistant",
        "ts": now,
        "checks": checks,
        "service_state": _service_health_status(),
    }


def _handle_health() -> Dict[str, Any]:
    # Backward-compat lightweight health; do NOT call external providers.
    ready = _health_ready()
    cfg = None
    try:
        cfg = load_config()
    except Exception:
        pass
    return {
        "status": ("ok" if ready.get("ok") else "degraded"),
        "llm_ready": bool(((ready.get("checks") or {}).get("llm_proxy") or {}).get("ok")),
        "provider": {"note": "skipped_in_light_health"},
        "time": str(ready.get("ts") or datetime.now().isoformat()),
        # extras for richer UI
        "run_mode": getattr(cfg, "run_mode", None),
        "dev_mode": getattr(cfg, "dev_mode", None),
        "recommend_mode": getattr(cfg, "recommend_mode", None),
        "recommend_modes": recommend_list_modes(),
        "service": ready,
    }


def _resolve_ohlcv_dev_mode(request_mode: Optional[str]) -> bool:
    cfg = load_config()
    m = (request_mode or "").strip().lower()

    if m in {"dev", "mock", "fixture"}:
        return True
    if m in {"default", "prod", "real", "live"}:
        return False

    return bool(cfg.dev_mode)


def _filter_bars_by_date(bars: List[Dict[str, Any]], start: Optional[str], end: Optional[str]) -> List[Dict[str, Any]]:
    if not bars:
        return bars
    if not start and not end:
        return bars

    def _ok(d: str) -> bool:
        if start and d < start:
            return False
        if end and d > end:
            return False
        return True

    return [b for b in bars if _ok(str(b.get("date", "")))]


def _handle_ohlcv(symbol: str, start: Optional[str], end: Optional[str], limit: int, mode: Optional[str]) -> OHLCVResp:
    # dev fixture route: no provider / no network
    if _resolve_ohlcv_dev_mode(mode):
        bars, meta = dev_ohlcv_bars(symbol, as_of=end, limit=limit)
        bars = _filter_bars_by_date(bars, start=start, end=end)
        if limit and limit > 0:
            bars = bars[-limit:]
        meta_out = dict(meta or {})
        meta_out.setdefault("filtered", {})
        meta_out["filtered"].update({k: v for k, v in {"start": start, "end": end, "limit": limit, "mode": "dev"}.items() if v is not None})
        return OHLCVResp(symbol=symbol, meta=meta_out, bars=[OHLCVBar(**b) for b in bars])

    # real mode (lazy import to avoid heavy deps on app import)
    from ..recommend.datahub import MarketDataHub  # local import
    hub = MarketDataHub()
    as_of = end  # prefer end as as_of boundary if provided
    df, meta = hub.daily_ohlcv(symbol, as_of=as_of, min_len=0)

    if not isinstance(df, pd.DataFrame) or df.empty:
        return OHLCVResp(symbol=symbol, meta=meta or {}, bars=[])

    dff = df.copy()
    if start:
        dff = dff[dff["date"] >= pd.to_datetime(start)]
    if end:
        dff = dff[dff["date"] <= pd.to_datetime(end)]
    if limit and limit > 0:
        dff = dff.tail(limit)

    def _bar_row(row: pd.Series) -> Dict[str, Any]:
        return {
            "date": pd.to_datetime(row["date"]).date().isoformat(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume", 0.0) or 0.0),
            "amount": float(row.get("amount", 0.0) or 0.0),
        }

    bars2: List[Dict[str, Any]] = [_bar_row(r) for _, r in dff.reset_index(drop=True).iterrows()]

    meta_out = dict(meta or {})
    meta_out.setdefault("filtered", {})
    meta_out["filtered"].update({k: v for k, v in {"start": start, "end": end, "limit": limit, "mode": "default"}.items() if v is not None})

    return OHLCVResp(symbol=symbol, meta=meta_out, bars=[OHLCVBar(**b) for b in bars2])


def _normalize_reco_obj(obj: Dict[str, Any]) -> Dict[str, Any]:
    # Use service mode normalizer to v1 (picks+meta)
    try:
        from ..recommend.modes import service as _svc

        return _svc._normalize_to_v1(obj)  # type: ignore[attr-defined]
    except Exception:
        # Best-effort minimal fallback
        picks = obj.get("picks") if isinstance(obj, dict) else []
        meta = {
            "as_of": obj.get("as_of") if isinstance(obj, dict) else None,
            "as_of_ts": obj.get("as_of_ts") if isinstance(obj, dict) else None,
            "timezone": (obj.get("timezone") if isinstance(obj, dict) else None) or "Asia/Shanghai",
            "tradeable": bool((obj.get("tradeable") if isinstance(obj, dict) else False)),
            "message": obj.get("message") if isinstance(obj, dict) else None,
            "disclaimer": obj.get("disclaimer") if isinstance(obj, dict) else None,
            "stage": obj.get("stage") if isinstance(obj, dict) else None,
            "debug": {"mode": "service", "degraded": True, "degrade_reasons": [{"reason_code": "NORMALIZE_FAILED"}]},
        }
        return {"picks": picks or [], "meta": meta}


def _handle_recommend_by_date(date: str) -> Dict[str, Any]:
    path = store_dir() / "recommend" / f"{date}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"recommend file not found for date={date}")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return _normalize_reco_obj(obj)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"failed to read file: {e}") from e


def _handle_reco_latest() -> Dict[str, Any]:
    path = store_dir() / "recommend" / "latest.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="latest recommend not found")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return _normalize_reco_obj(obj)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"failed to read file: {e}") from e


def _handle_champion() -> Dict[str, Any]:
    path = store_dir() / "registry" / "champion.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="champion not found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"failed to read file: {e}") from e


def _handle_live_file(date: str, name: str) -> Dict[str, Any] | list[Dict[str, Any]]:
    base = results_dir() / "live_shadow" / date
    if name.endswith(".json"):
        p = base / name
        if not p.exists():
            raise HTTPException(status_code=404, detail=f"not found: {name}")
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"failed to read file: {e}") from e
    elif name.endswith(".csv"):
        p = base / name
        if not p.exists():
            raise HTTPException(status_code=404, detail=f"not found: {name}")
        try:
            import pandas as pd
            df = pd.read_csv(p)
            return df.to_dict(orient="records")
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"failed to read file: {e}") from e
    else:
        raise HTTPException(status_code=400, detail="unsupported file type")


# -------------------------
# API router (preferred for SPA)
# -------------------------
api = APIRouter(prefix="/api")


@api.post("/chat", response_model=ChatResp)
def api_post_chat(req: ChatReq) -> ChatResp:
    try:
        return _handle_chat(req)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@api.post("/recommend", response_model=RecommendResp)
def api_post_recommend(req: RecommendReq) -> RecommendResp:  # type: ignore[return-value]
    try:
        return _handle_recommend(req)
    except APIError:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@api.get("/recommend/modes")
def api_get_recommend_modes() -> Dict[str, Any]:
    cfg = load_config()
    return {
        "available": recommend_list_modes(),
        "default": cfg.recommend_mode,
        "dev_mode": cfg.dev_mode,
        "run_mode": cfg.run_mode,
    }


@api.get("/health", response_model=HealthResp)
def api_get_health() -> HealthResp:
    try:
        return HealthResp(**_handle_health())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@api.get("/health/live")
def api_get_health_live() -> Dict[str, Any]:
    try:
        return _health_live()
    except Exception as e:  # noqa: BLE001
        # liveness must be extremely robust
        return {"ok": False, "status": "error", "service": "gp-assistant", "ts": datetime.now().isoformat(), "error": str(e)}


@api.get("/health/ready")
def api_get_health_ready() -> Dict[str, Any]:
    try:
        return _health_ready()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "status": "error", "service": "gp-assistant", "ts": datetime.now().isoformat(), "error": str(e)}


@api.get("/ohlcv/{symbol}", response_model=OHLCVResp)
def api_get_ohlcv(
    symbol: str,
    start: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    end: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    limit: int = Query(default=800, ge=1, le=5000),
    mode: Optional[str] = Query(default=None, description="ohlcv mode: dev|default (default follows GP_DEV_MODE)"),
) -> OHLCVResp:
    try:
        return _handle_ohlcv(symbol, start, end, limit, mode)
    except ValueError as e:
        # data unavailable / not found
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@api.get("/ohlcv_min/{symbol}")
def api_get_ohlcv_min(symbol: str, period: int = Query(5), days: int = Query(5), adjust: str = Query("")) -> Dict[str, Any]:
    """Optional minute bars (feature flag). Returns 501 when disabled."""
    if os.getenv("GP_MINLINE_ENABLED", "0").strip().lower() not in {"1", "true", "on", "yes"}:
        raise HTTPException(status_code=501, detail={"error": "minline_disabled"})
    try:
        import akshare as ak  # type: ignore
        df = ak.stock_zh_a_hist_min_em(symbol=symbol, period=str(period), start_date=None, end_date=None, adjust=adjust)  # type: ignore
        if not isinstance(df, pd.DataFrame) or df.empty:
            return {"symbol": symbol, "bars": []}
        dff = df.tail(int(days) * 240)
        bars: List[Dict[str, Any]] = []
        for _, r in dff.iterrows():
            bars.append({
                "date": str(r.get("日期") or r.get("time") or r.get("date")),
                "open": float(r.get("开盘") or r.get("open") or 0.0),
                "high": float(r.get("最高") or r.get("high") or 0.0),
                "low": float(r.get("最低") or r.get("low") or 0.0),
                "close": float(r.get("收盘") or r.get("close") or 0.0),
                "volume": float(r.get("成交量") or r.get("volume") or 0.0),
                "amount": float(r.get("成交额") or r.get("amount") or 0.0),
            })
        return {"symbol": symbol, "bars": bars, "meta": {"period": period, "days": days, "adjust": adjust}}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail={"error": "minline_fetch_failed", "message": str(e)}) from e


@api.get("/recommend/{date}")
def api_get_recommend_by_date(date: str) -> Dict[str, Any]:
    try:
        return _handle_recommend_by_date(date)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@api.get("/reco/latest")
def api_get_reco_latest() -> Dict[str, Any]:
    try:
        return _handle_reco_latest()
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@api.get("/reco/{date}")
def api_get_reco_by_date(date: str) -> Dict[str, Any]:
    try:
        return _handle_recommend_by_date(date)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@api.get("/champion")
def api_get_champion() -> Dict[str, Any]:
    try:
        return _handle_champion()
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@api.get("/live/{date}/metrics")
def api_get_live_metrics(date: str) -> Dict[str, Any]:
    try:
        data = _handle_live_file(date, "metrics.json")
        assert isinstance(data, dict)
        return data
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@api.get("/live/{date}/equity")
def api_get_live_equity(date: str) -> Dict[str, Any]:
    try:
        rows = _handle_live_file(date, "equity.csv")
        assert isinstance(rows, list)
        return {"date": date, "rows": rows}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@api.get("/live/{date}/orders")
def api_get_live_orders(date: str) -> Dict[str, Any]:
    try:
        rows = _handle_live_file(date, "order_log.csv")
        assert isinstance(rows, list)
        return {"date": date, "rows": rows}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Event/sync APIs ---

@api.post("/sync", response_model=SyncResp)
def api_post_sync(req: SyncReq) -> SyncResp:  # type: ignore[return-value]
    ack: Dict[str, str] = {}

    # Pre-ensure conversations minimally once per conv to reduce contention
    try:
        conv_ids = {ev.conversation_id for ev in req.outbox_events}
        for cid in conv_ids:
            try:
                event_store.ensure_conversation(cid)
                event_store.ensure_participant(cid)
            except Exception:
                pass
    except Exception:
        pass

    for ev in req.outbox_events:
        try:
            seq, _ = event_store.append_event(
                ev.conversation_id,
                event_id=ev.id,
                type=ev.type,
                data=ev.data,
                actor_id=ev.actor_id,
            )
            if ev.type == "read.updated":
                try:
                    last_read_seq = int((ev.data or {}).get("last_read_seq") or 0)
                    if last_read_seq > 0:
                        event_store.update_read(ev.conversation_id, ev.actor_id, last_read_seq)
                except Exception:
                    pass
            ack[ev.id] = f"accepted:{seq}"
        except Exception as e:  # noqa: BLE001
            ack[ev.id] = f"error:{e}"

    deltas: Dict[str, List[EventOut]] = {}
    for cid, last_seq in (req.conv_cursors or {}).items():
        try:
            events = event_store.list_events_after(cid, int(last_seq or 0), limit=200)
            deltas[cid] = [EventOut(**e) for e in events]
        except Exception:
            deltas[cid] = []

    conversations_delta = event_store.list_conversations()

    return SyncResp(
        ack=ack,
        deltas=deltas,
        conversations_delta=conversations_delta,
        user_settings_delta=[],
    )


# -------------------------
# Read-model endpoints (Phase 1)
# -------------------------

def _sql_conn():
    try:
        # best-effort reuse of event_store connection helper
        return event_store._connect()  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"failed to connect event store: {e}")


def _current_user_id_safe() -> str:
    try:
        return event_store._current_user_id()  # type: ignore[attr-defined]
    except Exception:
        return "local"


def _get_last_read_seq(cid: str, user_id: Optional[str] = None) -> int:
    uid = user_id or _current_user_id_safe()
    try:
        conn = _sql_conn()
        cur = conn.execute(
            "SELECT last_read_seq FROM participants WHERE conversation_id=? AND user_id=?",
            (cid, uid),
        )
        row = cur.fetchone()
        conn.close()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def _row_payload_to_obj(val: Optional[str]) -> Optional[Dict[str, Any]]:
    if val is None:
        return None
    try:
        return json.loads(val)
    except Exception:
        return None


def _map_kind_and_preview(kind: str, content: Optional[str], payload: Optional[Dict[str, Any]]):
    # Map storage rows to stable kind + preview string
    k = (kind or "text").strip().lower()
    if k == "text":
        pv = (content or "").strip()
        return "text", pv
    if k == "card":
        ptype = str((payload or {}).get("type") or "").strip().lower()
        if ptype == "recommendation":
            picks = (payload or {}).get("picks")
            n = 0
            if isinstance(picks, list):
                n = len(picks)
            return "recommendation", f"推荐清单 {n}"
        if ptype == "status":
            msg = str((payload or {}).get("message") or (payload or {}).get("content") or "状态更新")
            return "status", msg
        if ptype == "kline":
            # Do not treat K线为主要线程项；预览保守返回空
            return "status", ""
    # fallback
    return "text", (content or "").strip()


def _last_item_info(cid: str) -> Dict[str, Any]:
    conn = _sql_conn()
    try:
        cur = conn.execute(
            """
            SELECT id, seq_created, kind, content, payload, created_at
            FROM conv_messages
            WHERE conversation_id=? AND deleted_at IS NULL
            ORDER BY seq_created DESC
            LIMIT 50
            """,
            (cid,),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()
    for r in rows:
        mid, seq, kind, content, payload_json, created_at = r
        payload = _row_payload_to_obj(payload_json)
        kind2, preview = _map_kind_and_preview(kind or "", content, payload)
        # Skip pure kline (mapped to empty preview)
        if kind2 == "status" and preview == "":
            continue
        return {
            "id": str(mid),
            "seq": int(seq or 0),
            "kind": kind2,
            "preview": str(preview or ""),
            "created_at": created_at,
        }
    return {"id": None, "seq": 0, "kind": "text", "preview": "", "created_at": None}


def _unread_count(cid: str, last_read_seq: int) -> int:
    conn = _sql_conn()
    try:
        cur = conn.execute(
            """
            SELECT seq_created, kind, content, payload
            FROM conv_messages
            WHERE conversation_id=? AND deleted_at IS NULL AND seq_created>?
            ORDER BY seq_created ASC
            """,
            (cid, int(last_read_seq)),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()
    cnt = 0
    for seq, kind, content, payload_json in rows:
        payload = _row_payload_to_obj(payload_json)
        kind2, preview = _map_kind_and_preview(kind or "", content, payload)
        # Count as unread when it's a visible thread item (text/recommendation/status)
        if kind2 in {"text", "recommendation", "status"}:
            # Skip empty preview-only status (e.g., kline)
            if kind2 == "status" and preview == "":
                continue
            cnt += 1
    return cnt


@api.get("/conversations/summaries")
def api_get_conversation_summaries() -> List[Dict[str, Any]]:
    items = event_store.list_conversations()
    out: List[Dict[str, Any]] = []
    for m in items:
        cid = str(m.get("id"))
        title = str(m.get("title") or cid)
        last_seq = int(m.get("last_seq") or 0)
        updated_at = m.get("updated_at")
        last = _last_item_info(cid)
        last_read = _get_last_read_seq(cid)
        unread = _unread_count(cid, last_read)
        out.append(
            {
                "id": cid,
                "title": title,
                "last_seq": last_seq,
                "last_item_preview": last.get("preview") or "",
                "last_item_kind": last.get("kind") or "text",
                "last_item_ts": last.get("created_at"),
                "unread_count": unread,
                "updated_at": updated_at,
            }
        )
    return out


def _map_row_to_thread_item(row: tuple, cid: str) -> Optional[Dict[str, Any]]:
    # row columns: id, seq_created, author_id, kind, content, payload, created_at
    mid, seq, author_id, kind, content, payload_json, created_at = row
    payload = _row_payload_to_obj(payload_json)
    role = "assistant" if (str(author_id or "").lower().strip() == "assistant") else "user"
    # Status items can be mapped to system role optionally
    k2, _prev = _map_kind_and_preview(kind or "", content, payload)
    if k2 == "status" and _prev == "":
        # skip kline-like cards from thread items
        return None
    base = {
        "id": str(mid),
        "conversation_id": cid,
        "seq": int(seq or 0),
        "created_at": created_at,
        "role": ("system" if k2 == "status" else role),
    }
    if k2 == "text":
        return {**base, "kind": "text", "content": str(content or "")}
    if k2 == "recommendation":
        # Prefer v2 summary embedded in payload
        try:
            summ = (payload or {}).get("summary") or {}
            if isinstance(summ, dict) and summ.get("top_symbols") is not None:
                return {
                    **base,
                    "kind": "recommendation",
                    "artifact_id": str(mid),
                    "summary": {
                        "total": int(summ.get("total") or 0),
                        "top_symbols": [str(s) for s in (summ.get("top_symbols") or []) if isinstance(s, (str, int))],
                    },
                }
        except Exception:
            pass
        # Fallback: infer from legacy picks in payload
        picks = []
        try:
            picks = (payload or {}).get("picks") or []
        except Exception:
            picks = []
        top_symbols: List[str] = []
        if isinstance(picks, list):
            for p in picks[:3]:
                sym = p.get("symbol") if isinstance(p, dict) else None
                if isinstance(sym, str):
                    top_symbols.append(sym)
        return {
            **base,
            "kind": "recommendation",
            "artifact_id": str(mid),
            "summary": {"total": len(picks) if isinstance(picks, list) else 0, "top_symbols": top_symbols},
        }
    if k2 == "status":
        msg = None
        code = None
        try:
            msg = (payload or {}).get("message") or (payload or {}).get("content")
            code = (payload or {}).get("code")
        except Exception:
            pass
        return {**base, "kind": "status", "message": (str(msg) if msg is not None else None), "code": (str(code) if code is not None else None)}
    return None


@api.get("/threads/{cid}/items")
def api_get_thread_items(
    cid: str,
    anchor: Optional[int] = Query(default=None),
    direction: str = Query(default="backward", pattern="^(backward|forward)$"),
    limit: int = Query(default=60, ge=1, le=500),
) -> List[Dict[str, Any]]:
    # Query from conv_messages for stable thread items
    conn = _sql_conn()
    try:
        if direction == "forward":
            a = int(anchor or 0)
            cur = conn.execute(
                """
                SELECT id, seq_created, author_id, kind, content, payload, created_at
                FROM conv_messages
                WHERE conversation_id=? AND deleted_at IS NULL AND seq_created>?
                ORDER BY seq_created ASC
                LIMIT ?
                """,
                (cid, a, int(limit)),
            )
            rows = cur.fetchall() or []
        else:
            # backward: take items with seq<=anchor, ordered desc then reverse
            last = int(anchor or 10**12)
            cur = conn.execute(
                """
                SELECT id, seq_created, author_id, kind, content, payload, created_at
                FROM conv_messages
                WHERE conversation_id=? AND deleted_at IS NULL AND seq_created<=?
                ORDER BY seq_created DESC
                LIMIT ?
                """,
                (cid, last, int(limit)),
            )
            rows = list(reversed(cur.fetchall() or []))
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        it = _map_row_to_thread_item(r, cid)
        if it is not None:
            out.append(it)
    return out


@api.post("/threads/{cid}/read")
def api_post_thread_read(cid: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        last_read_seq = int((payload or {}).get("last_read_seq") or 0)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid last_read_seq: {e}") from e
    try:
        event_store.update_read(cid, None, last_read_seq)
        return {"status": "ok"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@api.post("/compare", response_model=CompareResp)
def api_post_compare(req: 'CompareReq') -> Dict[str, Any]:
    """Structured compare directly from artifact (no LLM)."""
    try:
        out = kernel_compare_symbols(req.run_id, req.symbols)
        return out
    except Exception as e:  # noqa: BLE001
        # sanitize: do not leak raw exception
        return {"ok": False, "error": "compare_unavailable"}


@api.get("/pick", response_model=PickDetailResp)
def api_get_pick_detail(run_id: Optional[str] = Query(default=None), symbol: str = Query(...)) -> Dict[str, Any]:
    try:
        out = kernel_pick_detail(run_id, symbol)
        return out
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "pick_detail_unavailable"}


## Legacy v1/v2 read helpers removed; unified artifact store is used instead.


def _recommend_v2_read(run_id: Optional[str], as_of: Optional[str]) -> Dict[str, Any]:
    return kernel_get_artifact_v2(run_id=run_id, as_of=as_of)


@api.get("/recommend_v2", response_model=RecommendV2Resp)
def api_get_recommend_v2(
    run_id: Optional[str] = Query(default=None),
    as_of: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    try:
        return _recommend_v2_read(run_id, as_of)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        # sanitize raw error leakage
        return {"artifact_version": "v2", "ok": False, "error": "recommend_v2_unavailable"}


# ---- Phase 3: Validation read-only endpoints ----


@api.get("/validation/strategy/{strategy}", response_model=StrategyValidationResp)
def api_get_strategy_validation(strategy: str) -> Dict[str, Any]:
    try:
        return kernel_strategy_validation(strategy)
    except Exception:
        return {"strategy": strategy, "event_stats": {"available": False}, "walk_forward": {"available": False}, "strategy_health": {"available": False}}


@api.get("/paperfolio", response_model=PaperfolioResp)
def api_get_paperfolio() -> Dict[str, Any]:
    try:
        return kernel_get_paperfolio()
    except Exception:
        return {"available": False, "picks": []}


@api.get("/live_shadow/summary", response_model=LiveShadowResp)
def api_get_live_shadow_summary() -> Dict[str, Any]:
    from ..kernel.facade import get_live_shadow_latest_summary
    try:
        return get_live_shadow_latest_summary()
    except Exception:
        return {"available": False, "dates": [], "summary": {}}


@api.get("/validation/summary", response_model=ValidationSummaryResp)
def api_get_validation_summary() -> Dict[str, Any]:
    try:
        from ..kernel.facade import get_validation_summary
        return get_validation_summary()
    except Exception:
        return {"as_of": None, "parts": {}}


@api.get("/recommend_v2/gated")
def api_get_recommend_v2_gated(
    run_id: Optional[str] = Query(default=None),
    as_of: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    try:
        from ..kernel.facade import get_gated_artifact_v2
        return get_gated_artifact_v2(run_id=run_id, as_of=as_of)
    except Exception:
        return {"artifact_version": "v2", "ok": False, "error": "recommend_v2_unavailable"}


# ---- Phase 7: Execution/Portfolio ----


@api.get("/portfolio", response_model=PortfolioResp)
def api_get_portfolio() -> Dict[str, Any]:
    try:
        from ..kernel.facade import get_portfolio_state
        return get_portfolio_state()
    except Exception:
        return {"as_of": None, "positions": [], "pending_intents": [], "recent_events": []}


@api.get("/execution/events")
def api_get_execution_events(limit: int = Query(100, ge=1, le=1000)) -> List[Dict[str, Any]]:
    try:
        from ..kernel.facade import get_execution_events
        return get_execution_events(limit)
    except Exception:
        return []


@api.post("/execution/paper/run")
def api_post_run_paper_execution(run_id: Optional[str] = Query(default=None), as_of: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    try:
        from ..kernel.facade import run_paper_execution
        res = run_paper_execution(run_id=run_id, as_of=as_of)
        return res
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "paper_execution_failed"}


# ---- Phase 8: Operator / Workbench ----


@api.get("/workbench", response_model=WorkbenchResp)
def api_get_workbench(run_id: Optional[str] = Query(default=None), as_of: Optional[str] = Query(default=None), event_limit: int = Query(100, ge=1, le=1000)) -> Dict[str, Any]:
    try:
        from ..operator.facade import get_workbench_snapshot
        return get_workbench_snapshot(run_id=run_id, as_of=as_of, event_limit=event_limit)
    except Exception:
        return {"as_of": None, "warnings": ["workbench_unavailable"]}


@api.post("/operator/intent/action", response_model=OperatorIntentActionResp)
def api_post_operator_intent_action(payload: OperatorIntentActionReq) -> Dict[str, Any]:
    try:
        from ..execution.actions import admit_intent, reject_intent, cancel_intent
        act = str(payload.action)
        if act == 'admit':
            if not payload.symbol:
                return {"ok": False, "error": "SYMBOL_REQUIRED"}
            return admit_intent(run_id=payload.run_id, as_of=payload.as_of, symbol=payload.symbol, note=payload.operator_note)
        elif act == 'reject':
            if not payload.symbol:
                return {"ok": False, "error": "SYMBOL_REQUIRED"}
            return reject_intent(run_id=payload.run_id, as_of=payload.as_of, symbol=payload.symbol, note=payload.operator_note)
        elif act == 'cancel':
            if not payload.intent_id:
                return {"ok": False, "error": "INTENT_ID_REQUIRED"}
            return cancel_intent(intent_id=payload.intent_id, note=payload.operator_note)
        return {"ok": False, "error": "UNKNOWN_ACTION"}
    except Exception:
        return {"ok": False, "error": "operator_action_failed"}


def _message_text_by_id(mid: str) -> Optional[str]:
    conn = _sql_conn()
    try:
        cur = conn.execute(
            "SELECT content FROM conv_messages WHERE id=? AND deleted_at IS NULL",
            (mid,),
        )
        row = cur.fetchone()
        return (row[0] if row else None) or None
    finally:
        conn.close()


def _build_preview_with_highlight(text: str, q: str, max_len: int = 120) -> Dict[str, Any]:
    s = text or ""
    if not q:
        return {"preview": s[:max_len], "highlights": []}
    s_low = s.lower()
    q_low = q.lower()
    idx = s_low.find(q_low)
    if idx < 0:
        return {"preview": s[:max_len], "highlights": []}
    start = max(0, idx - 16)
    end = min(len(s), idx + len(q) + 16)
    snippet = s[start:end]
    return {"preview": snippet, "highlights": [{"start": idx - start, "length": len(q)}]}


@api.get("/search")
def api_search_hits(
    q: str = Query(..., description="Search query"),
    conversation_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> List[Dict[str, Any]]:
    # New typed search hits with preview and anchor
    hits = event_store.search_messages(q, conversation_id=conversation_id, limit=limit)
    out: List[Dict[str, Any]] = []
    for h in hits:
        msg_id = str(h.get("message_id"))
        cid = str(h.get("conversation_id"))
        seq = int(h.get("seq") or 0)
        txt = _message_text_by_id(msg_id) or ""
        pv = _build_preview_with_highlight(txt, q)
        out.append(
            {
                "conversation_id": cid,
                "seq": seq,
                "message_id": msg_id,
                "preview": pv["preview"],
                "highlights": pv["highlights"],
                "anchor": {"conversation_id": cid, "seq": seq},
            }
        )
    return out


@api.get("/search_legacy")
def api_search_legacy(
    q: str = Query(..., description="Search query"),
    conversation_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> List[Dict[str, Any]]:
    # Preserve old minimal shape for backward compatibility
    return event_store.search_messages(q, conversation_id=conversation_id, limit=limit)


def _get_recommendation_artifact_by_mid(mid: str) -> Dict[str, Any]:
    conn = _sql_conn()
    try:
        cur = conn.execute(
            """
            SELECT id, conversation_id, seq_created, author_id, kind, content, payload, created_at
            FROM conv_messages
            WHERE id=? AND deleted_at IS NULL
            """,
            (mid,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="artifact not found")
    _id, _cid, _seq, _author, kind, _content, payload_json, _created = row
    if str(kind or "").lower() != "card":
        raise HTTPException(status_code=400, detail="not a card artifact")
    payload = _row_payload_to_obj(payload_json) or {}
    if str((payload or {}).get("type") or "").lower() != "recommendation":
        raise HTTPException(status_code=400, detail="not a recommendation artifact")
    # New: V2 run_id-based recommendation card -> read gated artifact and map to safe structure
    try:
        if str((payload or {}).get("artifact_version") or "").lower() == "v2" and (payload or {}).get("run_id"):
            from ..kernel.facade import get_gated_artifact_v2 as _get_gated  # local import to avoid heavy deps on app import
            run_id = str((payload or {}).get("run_id") or "")
            as_of = (payload or {}).get("as_of")
            art = _get_gated(run_id=run_id or None, as_of=as_of)
            # sanitize fields for frontend (do not leak internals)
            items_out: List[Dict[str, Any]] = []
            for it in (art.get("items") or []):
                if not isinstance(it, dict):
                    continue
                item = {
                    "symbol": str(it.get("symbol", "")),
                    "name": (it.get("name") if isinstance(it.get("name"), str) else None),
                    "strategy": (it.get("strategy") if isinstance(it.get("strategy"), str) else None),
                    "strategy_label": (it.get("strategy_label") if isinstance(it.get("strategy_label"), str) else None),
                    "thesis": (it.get("thesis") if isinstance(it.get("thesis"), str) else None),
                    "entry_zone": it.get("entry_zone"),
                    "stop": it.get("stop"),
                    "take_profit": it.get("take_profit"),
                    "reward_risk": it.get("reward_risk"),
                    "execution_state": it.get("execution_state"),
                    "actionable": it.get("actionable"),
                    "alpha_score": it.get("alpha_score"),
                    "execution_score": it.get("execution_score"),
                    "reliability_score": it.get("reliability_score"),
                    "final_score": it.get("final_score"),
                    "confidence": it.get("confidence"),
                    "risk_flags": it.get("risk_flags"),
                    "invalidation": it.get("invalidation"),
                    "gating_decision": (lambda gd: ({
                        "decision": gd.get("decision"),
                        "reasons": gd.get("reasons"),
                        "warnings": gd.get("warnings"),
                    } if isinstance(gd, dict) else None))(it.get("gating_decision")),
                }
                items_out.append(item)
            # Lightweight rationale summaries
            try:
                items = art.get("items") or []
                allow_n = sum(1 for it in items if isinstance(it, dict) and ((it.get("gating_decision") or {}).get("decision") == "allow"))
                blocked_n = sum(1 for it in items if isinstance(it, dict) and ((it.get("gating_decision") or {}).get("decision") == "blocked"))
                degraded_n = sum(1 for it in items if isinstance(it, dict) and ((it.get("gating_decision") or {}).get("decision") == "degraded"))
                run_reasons = ((art.get("run_gating") or {}).get("reasons") or [])
                selection_rationale = f"allow={allow_n}, degraded={degraded_n}; run_rules={', '.join(run_reasons or [])}"
                rejection_summary = f"blocked={blocked_n}"
            except Exception:
                selection_rationale = None
                rejection_summary = None

            v2_out = {
                "artifact_version": "v2",
                "run_id": art.get("run_id"),
                "as_of": art.get("as_of"),
                "market_regime": art.get("market_regime"),
                "degraded": bool(art.get("degraded")),
                "tradeable": bool(art.get("tradeable")),
                "reason": art.get("reason"),
                "risk_profile": art.get("risk_profile"),
                "universe_name": art.get("universe_name"),
                "symbols": art.get("symbols") or [],
                "themes": art.get("themes") or [],
                "items": items_out,
                "fallback_used": bool(art.get("fallback_used", False)),
                "run_gating": (lambda rg: ({
                    "decision": rg.get("decision"),
                    "reasons": rg.get("reasons"),
                    "warnings": rg.get("warnings"),
                } if isinstance(rg, dict) else None))(art.get("run_gating")),
                "selection_rationale": selection_rationale,
                "rejection_summary": rejection_summary,
            }
            top_syms: List[str] = []
            try:
                for it in (art.get("items") or [])[:3]:
                    if isinstance(it, dict) and isinstance(it.get("symbol"), str):
                        top_syms.append(str(it.get("symbol")))
            except Exception:
                pass
            return {
                "id": str(_id),
                "artifact_version": "v2",
                "run_id": v2_out.get("run_id"),
                "as_of": v2_out.get("as_of"),
                "source": "gated_v2",
                "summary": {
                    "total": len(v2_out.get("items") or []),
                    "top_symbols": top_syms,
                    "tradeable": v2_out.get("tradeable"),
                    "market_regime": v2_out.get("market_regime"),
                    "run_gating": v2_out.get("run_gating"),
                    "reason": v2_out.get("reason"),
                },
                "v2": v2_out,
            }
    except Exception:
        # fall through to legacy mapping
        pass
    # Normalize to safe subset
    picks_in = payload.get("picks") or []
    picks_out: List[Dict[str, Any]] = []
    if isinstance(picks_in, list):
        for p in picks_in:
            if not isinstance(p, dict):
                continue
            item = {
                "symbol": str(p.get("symbol", "")),
                "name": (p.get("name") if isinstance(p.get("name"), str) else None),
                "theme": (p.get("theme") if isinstance(p.get("theme"), str) else None),
            }
            champ = p.get("champion") if isinstance(p.get("champion"), dict) else None
            if champ:
                item["champion"] = {"strategy": str(champ.get("strategy", "")), "score": (champ.get("score") if isinstance(champ.get("score"), (int, float)) else None)}
            tp = p.get("trade_plan") if isinstance(p.get("trade_plan"), dict) else None
            if tp:
                bands = tp.get("bands") if isinstance(tp.get("bands"), dict) else None
                actions = tp.get("actions") if isinstance(tp.get("actions"), dict) else None
                risk = tp.get("risk") if isinstance(tp.get("risk"), dict) else None
                item["trade_plan"] = {
                    "entry": tp.get("entry"),
                    "take": tp.get("take"),
                    "stop": tp.get("stop"),
                    "bands": {k: v for k, v in (bands or {}).items() if k in {"S1", "S2", "R1", "R2"}},
                    "actions": {k: v for k, v in (actions or {}).items() if k in {"window_A", "window_B"}},
                    "risk": {
                        "stop_loss": (risk or {}).get("stop_loss"),
                        "time_stop": (risk or {}).get("time_stop"),
                        "no_averaging_down": (risk or {}).get("no_averaging_down"),
                    },
                }
                # prune undefined keys
                item["trade_plan"] = {k: v for k, v in item["trade_plan"].items() if v is not None}
            chip = p.get("chip") if isinstance(p.get("chip"), dict) else None
            if chip:
                item["chip"] = {"model_used": chip.get("model_used")}
            picks_out.append(item)
    as_of = payload.get("as_of") or None
    timezone = payload.get("timezone") or "Asia/Shanghai"
    tradeable = payload.get("tradeable") if isinstance(payload.get("tradeable"), bool) else None
    disclaimer = payload.get("disclaimer") or None
    message = payload.get("message") or None
    meta_env_grade = None
    try:
        env = payload.get("env") or {}
        if isinstance(env, dict):
            meta_env_grade = env.get("grade")
    except Exception:
        pass
    diagnostics = None
    try:
        debug = payload.get("debug") or {}
        if isinstance(debug, dict):
            diagnostics = {
                "degraded": bool(debug.get("degraded") is True),
                "degrade_reasons": debug.get("degrade_reasons") or [],
            }
    except Exception:
        pass
    return {
        "id": str(_id),
        "as_of": (str(as_of) if as_of is not None else None),
        "timezone": str(timezone),
        "picks": picks_out,
        "tradeable": tradeable,
        "disclaimer": (str(disclaimer) if disclaimer is not None else None),
        "message": (str(message) if message is not None else None),
        "meta": {"env_grade": meta_env_grade} if meta_env_grade is not None else {},
        "diagnostics": diagnostics,
    }


@api.get("/artifacts/recommendations/{artifact_id}")
def api_get_recommendation_artifact(artifact_id: str) -> Dict[str, Any]:
    try:
        return _get_recommendation_artifact_by_mid(artifact_id)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@api.get("/conversations/{cid}/events", response_model=list[EventOut])
def api_get_events(
    cid: str,
    after: Optional[int] = Query(default=None),
    around: Optional[int] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    try:
        if around is not None:
            events = event_store.list_events_around(cid, int(around), limit=limit)
        else:
            events = event_store.list_events_after(cid, int(after or 0), limit=limit)
        return [EventOut(**e) for e in events]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@api.get("/conversations/{cid}/export")
def api_export_conversation(cid: str) -> Dict[str, Any]:
    try:
        return event_store.export_conversation(cid)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@api.post("/conversations/import")
def api_import_conversation(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        event_store.import_conversation(payload)
        conv = (payload.get("conversation") or {}).get("id")
        return {"status": "ok", "conversation_id": conv}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@api.delete("/conversations/{cid}")
def api_delete_conversation(cid: str) -> Dict[str, Any]:
    try:
        event_store.delete_conversation(cid)
        return {"status": "ok"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


@api.post("/conversations/cleanup")
def api_cleanup_conversations(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Cleanup all conversations and/or messages.
    Body: {"mode": "all" | "events_only"}
    """
    mode = (payload or {}).get("mode") or "all"
    try:
        event_store.cleanup_conversations(str(mode))
        return {"status": "ok", "mode": mode}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


# legacy search route is provided as /search_legacy (see below)


@api.post("/attachments/sign")
def api_post_attachments_sign(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a local upload path and a pseudo public URL.

    Minimal placeholder to integrate client side direct uploads.
    """
    try:
        filename = str(payload.get("filename") or f"upload-{datetime.now().timestamp():.0f}")
        filename = os.path.basename(filename).strip().replace("..", "_") or "upload.bin"

        att_dir = store_dir() / "attachments"
        att_dir.mkdir(parents=True, exist_ok=True)
        upload_path = str((att_dir / filename).resolve())

        return {"upload_path": upload_path, "public_url": f"/attachments/{filename}"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


app.include_router(api)

# -------------------------
# Legacy routes (kept, hidden from schema)
# -------------------------
# Default to compact for consistency.
@app.post("/chat", include_in_schema=False, response_model=ChatResp)
def post_chat(req: ChatReq) -> ChatResp:
    return _handle_chat(req)


@app.post("/recommend", include_in_schema=False, response_model=RecommendResp)
def post_recommend(req: RecommendReq) -> RecommendResp:  # type: ignore[return-value]
    return _handle_recommend(req)


@app.get("/health", include_in_schema=False, response_model=HealthResp)
def get_health() -> HealthResp:
    return HealthResp(**_handle_health())
