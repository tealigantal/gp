#!/usr/bin/env python3
from __future__ import annotations

"""
Minimal CLI to run Phase 5 validation refresh.

Usage:
  python scripts/run_validation_refresh.py
  python scripts/run_validation_refresh.py --strategies S1 S2
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure src on path for repo-local execution without PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gp_assistant.validation.runner import run_validation_refresh


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run validation refresh and write consolidated summary")
    ap.add_argument("--strategies", nargs="*", default=None, help="Optional strategy list to refresh")
    args = ap.parse_args(argv)
    res = run_validation_refresh(args.strategies)
    print(json.dumps({k: res.get(k) for k in ["ok","started_at","finished_at","updated_parts","failed_parts","summary_path","warnings"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
