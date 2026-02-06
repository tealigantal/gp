#!/usr/bin/env bash
set -euo pipefail
docker build -t gp:local .
docker run --rm gp:local python assistant.py --help || true

