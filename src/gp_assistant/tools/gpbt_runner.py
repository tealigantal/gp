from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path
from typing import List, Tuple


def run_gpbt(python_exe: str, repo_root: Path, subcmd: str, args: List[str], allow: List[str], timeout_sec: int = 600) -> Tuple[int, str, str, float]:
    if subcmd not in allow:
        raise ValueError(f"Subcommand not allowed: {subcmd}. Allowed: {allow}")
    cmd = [python_exe, str(repo_root / 'gpbt.py'), subcmd] + args
    t0 = time.time()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(repo_root))
    try:
        out, err = p.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return 124, out.decode('utf-8', errors='ignore'), 'TIMEOUT: ' + err.decode('utf-8', errors='ignore'), time.time() - t0
    out_s = _sanitize(out.decode('utf-8', errors='ignore'))
    err_s = _sanitize(err.decode('utf-8', errors='ignore'))
    return p.returncode, out_s[:2000], err_s[:2000], time.time() - t0


def _sanitize(s: str) -> str:
    # Remove obvious secrets patterns
    import re
    s = re.sub(r"sk-[A-Za-z0-9]{4,}", "sk-***", s)
    s = s.replace('DEEPSEEK_API_KEY', '***')
    return s
