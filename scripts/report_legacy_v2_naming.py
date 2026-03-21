from __future__ import annotations

import os
import re
import json
from pathlib import Path


def main() -> None:
    base = Path('store/recommend')
    v2_files = list(base.glob('*_v2.json')) if base.exists() else []
    date_like = 0
    run_like = 0
    examples_date: list[str] = []
    examples_run: list[str] = []
    re_date = re.compile(r'^(\d{8}|\d{4}-\d{2}-\d{2})_v2\.json$')
    for p in v2_files:
        name = p.name
        if re_date.match(name):
            date_like += 1
            if len(examples_date) < 5:
                examples_date.append(name)
        else:
            run_like += 1
            if len(examples_run) < 5:
                examples_run.append(name)
    report = {
        'dir': str(base),
        'total_v2_files': len(v2_files),
        'run_id_named': run_like,
        'date_named': date_like,
        'examples_run': examples_run,
        'examples_date': examples_date,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

