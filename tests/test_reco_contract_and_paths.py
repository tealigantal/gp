from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from src.service.pipeline import service_preopen
from src.gp_assistant.recommend.modes import service as service_mode
from src.service.symbols import canonicalize_ts_code


def _mock_paths(tmp: Path, *, sub: str = ""):
    base = tmp / sub if sub else tmp
    # create dirs
    (base / "store" / "recommend").mkdir(parents=True, exist_ok=True)
    (base / "store" / "registry").mkdir(parents=True, exist_ok=True)
    (base / "universe").mkdir(parents=True, exist_ok=True)
    (base / "results").mkdir(parents=True, exist_ok=True)
    (base / "data" / "raw").mkdir(parents=True, exist_ok=True)
    return base


def test_reco_schema_has_meta(tmp_path, monkeypatch):
    root = _mock_paths(tmp_path)
    # champion registry
    (root / "store" / "registry" / "champion.json").write_text(json.dumps({
        "strategy_type": "baseline",
        "params_hash": "x",
        "scenario": "base",
        "robust": {"robust_sharpe_p05": 0.0},
    }), encoding="utf-8")
    # candidate pool with one symbol
    (root / "universe" / "candidate_pool_20250106.csv").write_text("ts_code\n600519.SH\n", encoding="utf-8")

    # monkeypatch core.paths
    from src.gp_assistant.core import paths as core_paths

    monkeypatch.setattr(core_paths, "store_dir", lambda: root / "store")
    monkeypatch.setattr(core_paths, "results_dir", lambda: root / "results")
    monkeypatch.setattr(core_paths, "universe_dir", lambda: root / "universe")
    # run preopen
    service_preopen("20250106", topk=1)
    latest = json.loads((root / "store" / "recommend" / "latest.json").read_text(encoding="utf-8"))
    assert isinstance(latest.get("meta"), dict)
    dbg = latest["meta"].get("debug") or {}
    assert isinstance(dbg.get("degrade_reasons"), list)


def test_empty_picks_degraded(tmp_path, monkeypatch):
    root = _mock_paths(tmp_path)
    (root / "store" / "registry" / "champion.json").write_text(json.dumps({}), encoding="utf-8")
    # empty candidate pool
    (root / "universe" / "candidate_pool_20250106.csv").write_text("ts_code\n", encoding="utf-8")
    from src.gp_assistant.core import paths as core_paths

    monkeypatch.setattr(core_paths, "store_dir", lambda: root / "store")
    monkeypatch.setattr(core_paths, "results_dir", lambda: root / "results")
    monkeypatch.setattr(core_paths, "universe_dir", lambda: root / "universe")
    service_preopen("20250106", topk=3)
    obj = json.loads((root / "store" / "recommend" / "latest.json").read_text(encoding="utf-8"))
    meta = obj.get("meta") or {}
    assert isinstance(meta, dict)
    assert meta.get("tradeable") in (True, False)
    # empty picks => degraded true with EMPTY_PICKS
    dbg = meta.get("debug") or {}
    assert dbg.get("degraded") is True
    reasons = dbg.get("degrade_reasons") or []
    assert any(r.get("reason_code") == "EMPTY_PICKS" for r in reasons)


def test_paths_no_cwd(tmp_path, monkeypatch):
    # ensure writes use core.paths rather than CWD
    root = _mock_paths(tmp_path)
    sub = _mock_paths(tmp_path, sub="subdir")
    (root / "store" / "registry" / "champion.json").write_text("{}", encoding="utf-8")
    (root / "universe" / "candidate_pool_20250106.csv").write_text("ts_code\n600519.SH\n", encoding="utf-8")
    from src.gp_assistant.core import paths as core_paths
    monkeypatch.setattr(core_paths, "store_dir", lambda: root / "store")
    monkeypatch.setattr(core_paths, "results_dir", lambda: root / "results")
    monkeypatch.setattr(core_paths, "universe_dir", lambda: root / "universe")
    # change cwd away from repo root
    old = os.getcwd()
    os.chdir(str(sub))
    try:
        service_preopen("20250106", topk=1)
    finally:
        os.chdir(old)
    # file must be under core.paths.store_dir()
    assert (root / "store" / "recommend" / "latest.json").exists()


def test_symbol_canonicalization():
    ts, code, disp = canonicalize_ts_code("sh601869")
    assert ts == "601869.SH" and code == "601869" and disp == ts
    ts, code, disp = canonicalize_ts_code("002455")
    assert ts == "002455.SZ" and code == "002455" and disp == ts


def test_non_trading_day(tmp_path, monkeypatch):
    root = _mock_paths(tmp_path)
    # create calendar marking 20260301 as non trading
    cal = pd.DataFrame({"cal_date": ["20260228", "20260229", "20260301", "20260302"], "is_open": [1, 1, 0, 1]})
    cal.to_parquet(root / "data" / "raw" / "trade_calendar.parquet", index=False)
    from src.gp_assistant.core import paths as core_paths
    monkeypatch.setattr(core_paths, "data_dir", lambda: root / "data")
    # simulate service reader on explicit non-trading date
    out = service_mode.run(date="2026-03-01")
    assert isinstance(out.get("meta"), dict)
    meta = out["meta"]
    dbg = meta.get("debug") or {}
    # explicit non-trading date -> tradeable false + degraded true
    assert meta.get("tradeable") is False
    assert dbg.get("degraded") is True
    assert any(r.get("reason_code") == "NON_TRADING_DAY" for r in dbg.get("degrade_reasons") or [])

