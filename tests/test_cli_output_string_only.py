from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import json
import yaml


def run_once(tmp: Path, text: str) -> str:
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, str(repo_root / 'assistant.py'), 'chat', '--once', text]
    p = subprocess.run(cmd, cwd=str(tmp), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert p.returncode == 0, p.stderr or p.stdout
    return p.stdout.strip()


def test_output_is_single_json_line(tmp_path: Path):
    # workspace
    (tmp_path / 'configs').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'configs' / 'assistant.yaml').write_text('workspace_root: .\n', encoding='utf-8')
    (tmp_path / 'configs' / 'llm.yaml').write_text(yaml.safe_dump({'provider': 'mock', 'json_mode': True}, allow_unicode=True), encoding='utf-8')
    (tmp_path / 'universe').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'universe' / 'candidate_pool_20260106.csv').write_text('ts_code\n000001.SZ\n000002.SZ\n' + '\n'.join(['000001.SZ']*18), encoding='utf-8')
    out = run_once(tmp_path, '荐股')
    # Must be valid single-line JSON
    obj = json.loads(out)
    assert obj.get('schema_version') == 'gp.assistant.v1'
    assert 'ok' in obj


def test_print_text_mode(tmp_path: Path):
    (tmp_path / 'configs').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'configs' / 'assistant.yaml').write_text('workspace_root: .\n', encoding='utf-8')
    (tmp_path / 'configs' / 'llm.yaml').write_text(yaml.safe_dump({'provider': 'mock', 'json_mode': True}, allow_unicode=True), encoding='utf-8')
    (tmp_path / 'universe').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'universe' / 'candidate_pool_20260106.csv').write_text('ts_code\n000001.SZ\n000002.SZ\n' + '\n'.join(['000001.SZ']*18), encoding='utf-8')
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, str(repo_root / 'assistant.py'), 'chat', '--once', '荐股', '--print-text']
    p = subprocess.run(cmd, cwd=str(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert p.returncode == 0
    out = p.stdout.strip()
    assert 'schema_version' not in out
