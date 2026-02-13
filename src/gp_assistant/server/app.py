# 简介：FastAPI 服务入口，提供 /chat（对话）、/recommend（荐股）与 /health（健康检查）
# 的路由定义与错误处理，作为容器运行的主要 HTTP API 入口。
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Any, Dict, Optional
from datetime import datetime

from ..core.config import load_config
from ..core.errors import APIError
from ..chat.orchestrator import handle_message
from ..recommend import agent as rec_agent


app = FastAPI(title="gp_assistant", version="1.0.0")


class ChatReq(BaseModel):
    session_id: Optional[str] = None
    message: str


class RecommendReq(BaseModel):
    date: Optional[str] = None
    topk: Optional[int] = 3
    universe: Optional[str] = "auto"
    symbols: Optional[list[str]] = None
    risk_profile: Optional[str] = "normal"


@app.exception_handler(APIError)
async def api_error_handler(_, exc: APIError):  # noqa: ANN001
    return JSONResponse(status_code=exc.status_code, content=exc.to_json())


@app.post("/chat")
def post_chat(req: ChatReq) -> Dict[str, Any]:
    try:
        return handle_message(req.session_id, req.message)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/recommend")
def post_recommend(req: RecommendReq) -> Dict[str, Any]:
    try:
        return rec_agent.run(date=req.date, topk=req.topk or 3, universe=req.universe or "auto", symbols=req.symbols, risk_profile=req.risk_profile or "normal")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def get_health() -> Dict[str, Any]:
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
    }
