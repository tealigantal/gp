#!/usr/bin/env bash
set -euo pipefail

# Build and start services
docker compose up --build -d

# Secrets scan
docker compose run --rm gp python scripts/scan_secrets.py

# Run tests (offline)
docker compose run --rm gp pytest -q

# Selfcheck
docker compose run --rm gp python scripts/selfcheck.py

# Agent once
OUT=$(docker compose run --rm gp python assistant.py chat --once "荐股")
echo "$OUT"
echo "$OUT" | grep -E "荐股 Top[0-9]+"
