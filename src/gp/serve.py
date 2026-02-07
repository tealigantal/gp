from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Body

from .config import load_config
from .report.schema import validate_report
from .utils import load_json

# New pipeline endpoints (gp_core)
from gp_core.pipeline import Pipeline as CorePipeline, PipelineConfig as CorePipelineConfig


def create_app() -> FastAPI:
    cfg = load_config()
    app = FastAPI()
    # No implicit LLM; gp_core will read configs and fail fast if missing

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
    @app.post("/api/recommend")
    def api_recommend(payload: Dict[str, Any] = Body(...)):
        repo_root = Path(".").resolve()
        date = str(payload.get('date') or '') or None
        user_profile = payload.get('user_profile') or {}
        question = str(payload.get('question') or '')
        topk = int(payload.get('topk') or 3)
        pipeline = CorePipeline(repo_root, llm_cfg='configs/llm.yaml', search_cfg='configs/search.yaml', strategies_cfg=str(repo_root / 'configs' / 'strategies.yaml'), cfg=CorePipelineConfig(lookback_days=14, topk=topk, queries=['A股 市场 两周 摘要','指数 成交额 情绪','板块 轮动 热点']))
        run_id, A, sel, runs, champ, resp = pipeline.run(end_date=date or '', user_profile=user_profile, user_question=question, topk=topk)
        return {'run_id': run_id, 'response': resp}

    @app.get("/api/runs/{run_id}")
    def api_run_index(run_id: str):
        rd = Path('store') / 'pipeline_runs' / run_id
        idx = rd / 'index.json'
        if not idx.exists():
            raise HTTPException(status_code=404, detail='run not found')
        import json as _json
        return _json.loads(idx.read_text(encoding='utf-8'))

    @app.get("/api/runs/{run_id}/artifacts/{name}")
    def api_run_artifact(run_id: str, name: str):
        rd = Path('store') / 'pipeline_runs' / run_id
        p = rd / name
        if not p.exists():
            raise HTTPException(status_code=404, detail='artifact not found')
        if p.suffix.lower() in ('.json', '.jsonl', '.txt', '.md'):
            return p.read_text(encoding='utf-8')
        raise HTTPException(status_code=400, detail='unsupported artifact type')

    return app
