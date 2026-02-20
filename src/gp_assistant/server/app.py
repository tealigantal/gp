"""FastAPI application for gp_assistant.

Routes:
 - Legacy (kept for compatibility): /chat, /recommend, /health
 - New API (for SPA): /api/chat, /api/recommend, /api/health
 - Optional helpers: /api/ohlcv/{symbol}, /api/recommend/{date}

Also adds optional CORS support controlled by env GP_CORS_ORIGINS.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from ..core.config import load_config
from ..core.errors import APIError
from ..core.paths import store_dir
from ..chat.orchestrator import handle_message
from ..recommend import agent as rec_agent
from ..recommend.datahub import MarketDataHub
from .models import (
    ChatReq,
    ChatResp,
    HealthResp,
    OHLCVResp,
    RecommendReq,
    RecommendResp,
)


app = FastAPI(title="gp_assistant", version="1.1.0")


# Optional CORS (disabled by default)
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
    """Return a compact form for RecommendResp.

    Keeps only: as_of, timezone, env, themes, picks, tradeable, message,
    execution_checklist, disclaimer; and debug.{degraded,degrade_reasons,advisories}
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
        for k in ("degraded", "degrade_reasons", "advisories"):
            if k in dbg:
                slim[k] = dbg.get(k)
        if slim:
            out["debug"] = slim
    return out


def _handle_chat(req: ChatReq) -> ChatResp:
    data = handle_message(req.session_id, req.message)
    # Pack into ChatResp
    return ChatResp(
        session_id=data.get("session_id"),
        reply=str(data.get("reply", "")),
        tool_trace=data.get("tool_trace", {}),
    )


def _handle_recommend(req: RecommendReq) -> Dict[str, Any]:
    result = rec_agent.run(
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


def _handle_health() -> HealthResp:
    cfg = load_config()
    from ..providers.factory import get_provider

    provider = get_provider()
    now = datetime.now().isoformat()
    llm_ready = bool(cfg.llm_base_url and cfg.llm_api_key)
    return HealthResp(status="ok", llm_ready=llm_ready, provider=provider.healthcheck(), time=now)


def _handle_ohlcv(symbol: str, start: Optional[str], end: Optional[str], limit: int) -> OHLCVResp:
    hub = MarketDataHub()
    as_of = end  # prefer end date as as_of boundary if provided
    df, meta = hub.daily_ohlcv(symbol, as_of=as_of, min_len=0)

    if not isinstance(df, pd.DataFrame) or df.empty:
        return OHLCVResp(symbol=symbol, meta=meta or {}, bars=[])

    # Normalize and filter
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

    bars: List[Dict[str, Any]] = [
        _bar_row(r) for _, r in dff.reset_index(drop=True).iterrows()
    ]
    # Attach filter info
    meta_out = dict(meta or {})
    meta_out.setdefault("filtered", {})
    meta_out["filtered"].update({k: v for k, v in {"start": start, "end": end, "limit": limit}.items() if v is not None})
    return OHLCVResp(symbol=symbol, meta=meta_out, bars=bars)


def _handle_recommend_by_date(date: str) -> Dict[str, Any]:
    path = store_dir() / "recommend" / f"{date}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"recommend file not found for date={date}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"failed to read file: {e}")


# API router (preferred for SPA)
api = APIRouter(prefix="/api")


@api.post("/chat", response_model=ChatResp)
def api_post_chat(req: ChatReq) -> ChatResp:
    try:
        return _handle_chat(req)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@api.post("/recommend", response_model=RecommendResp)
def api_post_recommend(req: RecommendReq) -> RecommendResp:  # type: ignore[return-value]
    try:
        return _handle_recommend(req)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@api.get("/health", response_model=HealthResp)
def api_get_health() -> HealthResp:
    try:
        return _handle_health()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@api.get("/ohlcv/{symbol}", response_model=OHLCVResp)
def api_get_ohlcv(
    symbol: str,
    start: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    end: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    limit: int = Query(default=800, ge=1, le=5000),
) -> OHLCVResp:
    try:
        return _handle_ohlcv(symbol, start, end, limit)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@api.get("/recommend/{date}")
def api_get_recommend_by_date(date: str) -> Dict[str, Any]:
    try:
        return _handle_recommend_by_date(date)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


app.include_router(api)


# Legacy routes (kept, hidden from schema). Default to compact for consistency.
@app.post("/chat", include_in_schema=False, response_model=ChatResp)
def post_chat(req: ChatReq) -> ChatResp:
    return _handle_chat(req)


@app.post("/recommend", include_in_schema=False, response_model=RecommendResp)
def post_recommend(req: RecommendReq) -> RecommendResp:  # type: ignore[return-value]
    return _handle_recommend(req)


@app.get("/health", include_in_schema=False, response_model=HealthResp)
def get_health() -> HealthResp:
    return _handle_health()
