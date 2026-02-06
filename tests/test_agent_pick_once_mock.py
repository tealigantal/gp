from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import yaml

from tests.fixtures.min_data import seed_min_dataset


def test_agent_pick_once_mock(tmp_path: Path, monkeypatch):
    # Seed data under tmp workspace
    seed_min_dataset(tmp_path)
    # Write assistant + llm configs in tmp workspace
    (tmp_path / 'configs').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'configs' / 'assistant.yaml').write_text(yaml.safe_dump({'workspace_root': '.'}, allow_unicode=True), encoding='utf-8')
    # Minimal gpbt config for CLI subcommands
    cfg = {
        'provider': 'local_files',
        'data_root': 'data',
        'universe_root': 'universe',
        'results_root': 'results',
        'universe': {'min_list_days': 1, 'exclude_st': False, 'min_amount': 1.0, 'min_vol': 1},
        'bars': {'daily_adj': 'qfq', 'min_freq': '5min'},
        'fees': {'commission_rate': 0.0003, 'commission_cap': 0.0013, 'transfer_fee_rate': 0.00001, 'stamp_duty_rate': 0.0005, 'slippage_bps': 3, 'min_commission': 0},
        'experiment': {'candidate_size': 20, 'initial_cash': 1000000, 'run_id': 't'},
    }
    (tmp_path / 'configs' / 'config.yaml').write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding='utf-8')
    (tmp_path / 'configs' / 'llm.yaml').write_text(yaml.safe_dump({'provider': 'mock', 'json_mode': True}, allow_unicode=True), encoding='utf-8')
    # Invoke assistant one-shot; use absolute assistant.py path
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, str(repo_root / 'assistant.py'), 'chat', '--once', '荐股']
    p = subprocess.run(cmd, cwd=str(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert p.returncode == 0
    out = p.stdout.strip()
    # Must contain TopK and list items
    assert '荐股 Top' in out
    assert any(code in out for code in ['000001.SZ','000002.SZ','000003.SZ'])
    # Pick JSON persisted
    picks_dir = tmp_path / 'store' / 'assistant' / 'picks'
    assert picks_dir.exists()
    files = [x.name for x in picks_dir.glob('pick_20260106_*_*.json')]
    assert files, 'picks json not found'
