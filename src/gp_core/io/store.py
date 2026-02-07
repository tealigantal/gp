from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable


def _ts() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def _hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]


def new_run_dir(repo_root: Path, end_date: str) -> Path:
    base = Path(repo_root) / "store" / "pipeline_runs"
    base.mkdir(parents=True, exist_ok=True)
    rid = f"{_ts()}_{_hash(end_date)}"
    rd = base / rid
    (rd / "prompts").mkdir(parents=True, exist_ok=True)
    (rd / "llm_raw").mkdir(parents=True, exist_ok=True)
    (rd / "03_strategy_runs").mkdir(parents=True, exist_ok=True)
    return rd


def save_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def save_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def save_prompt(run_dir: Path, step: str, name: str, payload: Dict[str, Any]) -> Path:
    p = run_dir / "prompts" / f"{step}_{name}.json"
    save_json(p, payload)
    return p


def save_llm_raw(run_dir: Path, step: str, name: str, payload: Dict[str, Any]) -> Path:
    p = run_dir / "llm_raw" / f"{step}_{name}.json"
    save_json(p, payload)
    return p

