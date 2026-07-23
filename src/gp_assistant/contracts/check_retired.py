from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "docs" / "contracts" / "retired_symbols.json"


def main() -> int:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    blocked = tuple(config["blocked"])
    exceptions = {ROOT / path for path in config["exceptions"]}
    failures: list[str] = []
    for root_name in ("src", "tests", "frontend", "docs"):
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path in exceptions or path.suffix not in {".py", ".ts", ".tsx", ".md", ".json", ".yaml", ".yml"}:
                continue
            text = path.read_text(encoding="utf-8")
            for symbol in blocked:
                if symbol in text:
                    failures.append(f"retired_symbol:{path.relative_to(ROOT)}:{symbol}")
    if failures:
        raise SystemExit("\n".join(failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
