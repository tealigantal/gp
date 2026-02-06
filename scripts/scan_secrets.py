from __future__ import annotations

import os
import re
import sys
from pathlib import Path


PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{12,}"),
    re.compile(r"DEEPSEEK_API_KEY\s*=\s*sk-[A-Za-z0-9]+"),
    re.compile(r"OPENAI_API_KEY\s*=\s*sk-[A-Za-z0-9]+"),
]

EXCLUDES = {'.git', 'data', 'results', 'store', '.pytest_cache', '__pycache__', 'EMQuantAPI_Python'}
TEXT_SUFFIXES = {'.py','.md','.txt','.yaml','.yml','.json','.csv','.ini','.cfg'}


def is_text_file(p: Path) -> bool:
    return p.suffix.lower() in TEXT_SUFFIXES


def main() -> int:
    root = Path('.').resolve()
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        # prune excludes
        dirnames[:] = [d for d in dirnames if d not in EXCLUDES]
        for fn in filenames:
            p = Path(dirpath) / fn
            if not is_text_file(p):
                continue
            try:
                s = p.read_text(encoding='utf-8')
            except Exception:
                continue
            for pat in PATTERNS:
                for m in pat.finditer(s):
                    found.append((str(p), m.group(0)[:8] + '***'))
                    break
    if found:
        for f, sample in found:
            print(f"[leak?] {f}: {sample}")
        return 1
    print('No obvious secrets found.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

