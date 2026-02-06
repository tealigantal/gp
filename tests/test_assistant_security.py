from pathlib import Path
import pytest

from src.gp_assistant.tools.file_read import safe_read
from src.gp_assistant.tools.gpbt_runner import run_gpbt


def test_file_read_escape(tmp_path: Path):
    ws = tmp_path
    (ws / 'ok.txt').write_text('hi', encoding='utf-8')
    # normal read
    txt, n = safe_read('ok.txt', ws, allow_roots=[ws])
    assert 'hi' in txt
    # escape outside
    with pytest.raises(PermissionError):
        safe_read('../secrets.txt', ws, allow_roots=[ws])


def test_exec_allowlist(tmp_path: Path):
    # Subcommand not allowed
    import sys
    with pytest.raises(ValueError):
        run_gpbt(sys.executable, tmp_path, 'rm', ['-rf', '/'], allow=['backtest'])

