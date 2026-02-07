from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Body, Query

from .config import load_config
from .report.schema import validate_report
from .utils import load_json

# New pipeline endpoints
from src.gp_assistant.config import AssistantConfig
from src.gp_assistant.llm_client import SimpleLLMClient
from src.gp_research.market_info import MarketInfo, MarketInfoConfig
from src.gp_research.pipeline import RecommendPipeline, PipelineConfig


def create_app() -> FastAPI:
    cfg = load_config()
    app = FastAPI()
    # Prepare assistant cfg and llm client (optional)
    try:
        assistant_cfg = AssistantConfig.load()
        llm_client = SimpleLLMClient(assistant_cfg.llm.llm_config_file, {
            'temperature': assistant_cfg.llm.temperature,
            'max_tokens': assistant_cfg.llm.max_tokens,
            'timeout': assistant_cfg.llm.timeout,
        })
    except Exception:
        assistant_cfg = None  # type: ignore
        llm_client = None  # type: ignore

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/report/latest")
    def latest_report():
        latest = cfg.results / "latest_report.json"
        data = load_json(latest)
        if not data:
            raise HTTPException(status_code=404, detail="No report")
        validate_report(data)
        return data

    @app.get("/top10/latest")
    def top10_latest():
        latest = cfg.results / "latest_report.json"
        data = load_json(latest)
        if not data:
            raise HTTPException(status_code=404, detail="No report")
        return data.get("top10", [])

    @app.get("/plan/{code}")
    def plan(code: str):
        latest = cfg.results / "latest_report.json"
        data = load_json(latest)
        if not data:
            raise HTTPException(status_code=404, detail="No report")
        for it in data.get("top10", []):
            if it.get("code") == code.upper():
                return it.get("actions", {})
        raise HTTPException(status_code=404, detail="Not found")

    # New endpoints (pipeline)
    @app.get("/api/market_context")
    def api_market_context(end: str = Query(None), lookback: int = Query(14), provider: str = Query(None)):
        repo_root = Path(".").resolve()
        mi = MarketInfo(repo_root, cfg=MarketInfoConfig(provider=(provider or 'mock'), lookback_days=lookback, keywords=[]))
        ctx = mi.get(end_date=end, lookback_days=lookback, provider=provider or 'mock')
        return ctx.to_dict()

    @app.post("/api/recommend")
    def api_recommend(payload: Dict[str, Any] = Body(...)):
        repo_root = Path(".").resolve()
        date = str(payload.get('date') or '') or None
        user_profile = payload.get('user_profile') or {}
        question = str(payload.get('question') or '')
        topk = int(payload.get('topk') or 3)
        mode = str(payload.get('mode') or 'rule')
        pipeline = RecommendPipeline(repo_root, llm_client=llm_client, cfg=PipelineConfig(market_provider='mock', lookback_days=14, judge=mode, topk=topk))
        mc, sel, runs, champ, resp = pipeline.run(end_date=date, user_profile=user_profile, user_question=question, topk=topk)
        return resp.to_dict()

    return app
