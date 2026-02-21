#!/usr/bin/env bash
set -euo pipefail

echo "[1/2] compileall"
python -m compileall src/gp_assistant

echo "[2/2] pytest"
export STRICT_REAL_DATA=${STRICT_REAL_DATA:-0}
pytest -q

