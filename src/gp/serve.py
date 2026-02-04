from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException

from .config import load_config
from .report.schema import validate_report
from .utils import load_json


def create_app() -> FastAPI:
    cfg = load_config()
    app = FastAPI()

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

    return app

