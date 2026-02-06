from __future__ import annotations

import subprocess
import sys


def test_import_gp_assistant_and_pick():
    import gp_assistant  # noqa: F401
    import gp_assistant.actions.pick  # noqa: F401


def test_compileall_gp_assistant():
    # Compile the gp_assistant package to catch syntax/indentation errors
    cmd = [sys.executable, '-m', 'compileall', '-q', 'src/gp_assistant']
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert r.returncode == 0, r.stderr or r.stdout

