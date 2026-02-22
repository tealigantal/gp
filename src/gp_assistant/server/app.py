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
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..chat import event_store
from ..chat.orchestrator import handle_message
from ..core.config import load_config
from ..core.errors import APIError
from ..core.paths import store_dir
from ..dev.fixtures import dev_ohlcv_bars
from ..recommend.datahub import MarketDataHub
from ..recommend.runner import list_modes as recommend_list_modes
from ..recommend.runner import run as recommend_run
from .models import (
    ChatReq,
    ChatResp,
    EventOut,
    HealthResp,
    OHLCVBar,
    OHLCVResp,
    RecommendReq,
    RecommendResp,
    SyncReq,
    SyncResp,
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
    """
    Return a compact form for RecommendResp.

    Keeps only:
    - as_of, timezone, env, themes, picks, tradeable, message, execution_checklist, disclaimer
    - debug.{degraded,degrade_reasons,advisories,mode,dev_source}
    """
    keep_keys = {
        "as_of",
        "timezone",
        "env",
        "themes",
        "picks",
        "tradeable",
        "message",
        "execution_checklist",
        "disclaimer",
    }
    out: Dict[str, Any] = {k: payload.get(k) for k in keep_keys if k in payload}

    dbg = payload.get("debug") or {}
    if isinstance(dbg, dict):
        slim = {}
        for k in ("degraded", "degrade_reasons", "advisories", "mode", "dev_source"):
            if k in dbg:
                slim[k] = dbg.get(k)
        if slim:
            out["debug"] = slim

    return out


def _handle_chat(req: ChatReq) -> ChatResp:
    data = handle_message(req.session_id, req.message, getattr(req, "message_id", None))
    return ChatResp(
        session_id=data.get("session_id"),
        reply=str(data.get("reply", "")),
        tool_trace=data.get("tool_trace", {}),
        assistant_message_id=data.get("assistant_message_id"),
    )


def _handle_recommend(req: RecommendReq) -> Dict[str, Any]:
    # IMPORTANT: use runner (multi-mode)
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


def _handle_health() -> Dict[str, Any]:
    cfg = load_config()
    from ..providers.factory import get_provider

    provider = get_provider()
    now = datetime.now().isoformat()

    llm_ready = bool(cfg.llm_base_url and cfg.llm_api_key)

    return {
        "status": "ok",
        "llm_ready": llm_ready,
        "provider": provider.healthcheck(),
        "time": now,
        # extras (safe; HealthResp allows extra)
        "run_mode": cfg.run_mode,
        "dev_mode": cfg.dev_mode,
        "recommend_mode": cfg.recommend_mode,
        "recommend_modes": recommend_list_modes(),
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

    # real mode
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


def _handle_recommend_by_date(date: str) -> Dict[str, Any]:
    path = store_dir() / "recommend" / f"{date}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"recommend file not found for date={date}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"failed to read file: {e}") from e


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


@api.get("/recommend/{date}")
def api_get_recommend_by_date(date: str) -> Dict[str, Any]:
    try:
        return _handle_recommend_by_date(date)
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


@api.get("/search")
def api_search(
    q: str = Query(..., description="Search query"),
    conversation_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> List[Dict[str, Any]]:
    try:
        return event_store.search_messages(q, conversation_id=conversation_id, limit=limit)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e)) from e


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