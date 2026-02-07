from __future__ import annotations

from pathlib import Path
import json
import yaml

from src.gp_research.strategy_engine import judge_champion
from src.gp_research.schemas import StrategyRunResult
from src.gp_research.pipeline import RecommendPipeline, PipelineConfig
from tests.fixtures.min_data import seed_min_dataset


def test_judge_rule_selects_champion():
    runs = [
        StrategyRunResult(provider='mock', strategy_id='s1', name='S1', tags=['range'], period={'start':'20260101','end':'20260106'}, metrics={'win_rate':0.6,'avg_return':0.01,'max_drawdown':0.02,'turnover':0.1}),
        StrategyRunResult(provider='mock', strategy_id='s2', name='S2', tags=['trend'], period={'start':'20260101','end':'20260106'}, metrics={'win_rate':0.3,'avg_return':0.005,'max_drawdown':0.01,'turnover':0.1}),
    ]
    champ, why = judge_champion('range', runs)
    assert champ.strategy_id == 's1'
    assert 'wr=' in why


def test_pipeline_mock_end_to_end(tmp_path: Path, monkeypatch):
    # Seed dataset and minimal configs
    seed_min_dataset(tmp_path)
    (tmp_path / 'configs').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'configs' / 'assistant.yaml').write_text(yaml.safe_dump({'workspace_root': '.'}, allow_unicode=True), encoding='utf-8')
    (tmp_path / 'configs' / 'llm.yaml').write_text(yaml.safe_dump({'provider': 'mock', 'json_mode': True}, allow_unicode=True), encoding='utf-8')
    # Minimal gpbt config to allow llm_ranker mock
    cfg = {
        'provider': 'local_files',
        'data_root': 'data',
        'universe_root': 'universe',
        'results_root': 'results',
        'universe': {'min_list_days': 1, 'exclude_st': False, 'min_amount': 1.0, 'min_vol': 1},
        'bars': {'daily_adj': 'qfq', 'min_freq': '5min'},
        'fees': {'commission_rate': 0.0003, 'commission_cap': 0.0013, 'transfer_fee_rate': 0.00001, 'stamp_duty_rate': 0.0005, 'slippage_bps': 3, 'min_commission': 0},
        'experiment': {'candidate_size': 20, 'initial_cash': 1000000, 'run_id': 'pipeline'},
    }
    (tmp_path / 'configs' / 'config.yaml').write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding='utf-8')

    # Run pipeline
    monkeypatch.chdir(tmp_path)
    pipe = RecommendPipeline(tmp_path, llm_client=None, cfg=PipelineConfig(market_provider='mock', lookback_days=14, judge='rule', topk=3))
    mc, sel, runs, champ, resp = pipe.run(end_date='20260106', user_profile={'risk_level': 'neutral', 'topk': 3}, user_question='荐股', topk=3)
    # Check schema-like fields
    assert isinstance(resp.to_dict(), dict)
    assert resp.provider in ('fallback','mock','llm')
    assert resp.recommendations
    # Files persisted
    assert (tmp_path / 'store' / 'market_context' / '20260106.json').exists()
    assert any((tmp_path / 'store' / 'strategy_runs').glob('*_20260106.json'))
    assert (tmp_path / 'store' / 'pipeline_runs' / 'run_20260106.json').exists()

