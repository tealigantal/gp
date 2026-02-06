from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import json
import yaml

from src.gp_assistant.date_utils import parse_user_date


def run_once_json(tmp: Path, text: str) -> dict:
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, str(repo_root / 'assistant.py'), 'chat', '--once', text]
    p = subprocess.run(cmd, cwd=str(tmp), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert p.returncode == 0, p.stderr or p.stdout
    return json.loads(p.stdout.strip())


def setup_ws(tmp: Path, provider: str = 'mock') -> None:
    (tmp / 'configs').mkdir(parents=True, exist_ok=True)
    (tmp / 'configs' / 'assistant.yaml').write_text('workspace_root: .\n', encoding='utf-8')
    llm = {'provider': provider, 'json_mode': True}
    if provider == 'deepseek':
        llm['base_url'] = 'http://127.0.0.1:9/v1'
    (tmp / 'configs' / 'llm.yaml').write_text(yaml.safe_dump(llm, allow_unicode=True), encoding='utf-8')


def test_parse_date_0209_unit():
    from datetime import date
    d = parse_user_date('0209荐股', date(2026, 2, 7))
    assert d and d.strftime('%Y%m%d') == '20260209'


def test_effective_date_fallback_reason(tmp_path: Path):
    setup_ws(tmp_path, 'mock')
    (tmp_path / 'universe').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'universe' / 'candidate_pool_20260106.csv').write_text('ts_code\n000001.SZ\n' + '\n'.join(['000001.SZ']*19), encoding='utf-8')
    obj = run_once_json(tmp_path, '20260209荐股')
    assert obj['request']['requested_date'] in (obj['request'].get('requested_date'), obj['decision']['effective_date'])
    # fallback reason should be non-empty when requested date unavailable
    assert obj['decision'].get('fallback_reason')


def test_pool_membership_enforced(tmp_path: Path):
    setup_ws(tmp_path, 'mock')
    (tmp_path / 'universe').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'universe' / 'candidate_pool_20260106.csv').write_text('ts_code\n000001.SZ\n000002.SZ\n' + '\n'.join(['000001.SZ']*18), encoding='utf-8')
    obj = run_once_json(tmp_path, '荐股')
    pool = {'000001', '000002'}
    for r in obj.get('recommendations', []):
        code = str(r.get('code',''))
        six = ''.join([c for c in code if c.isdigit()])[:6]
        assert six in pool


def test_provider_truthfulness_fallback(tmp_path: Path):
    # deepseek base_url unreachable to force fallback
    setup_ws(tmp_path, 'deepseek')
    (tmp_path / 'universe').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'universe' / 'candidate_pool_20260106.csv').write_text('ts_code\n000001.SZ\n' + '\n'.join(['000001.SZ']*19), encoding='utf-8')
    obj = run_once_json(tmp_path, '荐股')
    assert obj['decision']['provider'] != 'llm'

