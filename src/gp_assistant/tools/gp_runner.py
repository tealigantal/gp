from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import List, Tuple


def run_gp(python_exe: str, repo_root: Path, subcmd: str, args: List[str], allow: List[str], timeout_sec: int = 600) -> Tuple[int, str, str, float]:
    if subcmd not in allow:
        raise ValueError(f"Subcommand not allowed: {subcmd}. Allowed: {allow}")
    cmd = [python_exe, str(repo_root / 'gp.py'), subcmd] + args
    t0 = time.time()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(repo_root))
    try:
        out, err = p.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return 124, out.decode('utf-8', errors='ignore'), 'TIMEOUT: ' + err.decode('utf-8', errors='ignore'), time.time() - t0
    return p.returncode, out.decode('utf-8', errors='ignore'), err.decode('utf-8', errors='ignore'), time.time() - t0

