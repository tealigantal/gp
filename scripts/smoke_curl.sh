#!/usr/bin/env bash
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:8000}"

echo "GET $BASE/api/health" && curl -sS "$BASE/api/health" || true
echo "POST $BASE/api/recommend" && curl -sS -X POST "$BASE/api/recommend" -H 'Content-Type: application/json' -d '{"topk":1,"universe":"symbols","symbols":["600519"],"detail":"compact"}' || true
echo "POST $BASE/api/chat" && curl -sS -X POST "$BASE/api/chat" -H 'Content-Type: application/json' -d '{"session_id":null,"message":"荐股 topk=1"}' || true
