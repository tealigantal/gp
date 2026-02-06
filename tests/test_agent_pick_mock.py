from __future__ import annotations

from pathlib import Path
import yaml

from src.gpbt.config import AppConfig, Paths, Fees, UniverseCfg, BarsCfg, ExperimentCfg
from src.gpbt.rankers.llm_ranker import rank as llm_rank
from tests.fixtures.min_data import seed_min_dataset


def test_agent_pick_mock(tmp_path, monkeypatch):
    # Seed data and switch CWD so llm_ranker reads configs/llm.yaml under tmp
    paths = seed_min_dataset(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'configs').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'configs' / 'llm.yaml').write_text(yaml.safe_dump({
        'provider': 'mock',
        'json_mode': True,
    }, allow_unicode=True), encoding='utf-8')
    cfg = AppConfig(
        provider='local_files',
        paths=Paths(data_root=paths['data_root'], universe_root=paths['universe_root'], results_root=paths['results_root']),
        fees=Fees(),
        universe=UniverseCfg(),
        bars=BarsCfg(),
        experiment=ExperimentCfg(run_id='mockpick')
    )
    df = llm_rank(cfg, '20260106', 'momentum_v1', force=True, topk=3)
    assert len(df) == 3
    assert set(df.columns) >= {'ts_code','rank'}
    # TopK parseable
    top_codes = df['ts_code'].astype(str).tolist()
    assert all(isinstance(c, str) and len(c) > 0 for c in top_codes)

