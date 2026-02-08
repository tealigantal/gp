from __future__ import annotations

import json
import sys
import time
import requests


def main() -> int:
    base = "http://127.0.0.1:8000"
    try:
        h = requests.get(base + "/health", timeout=5).json()
        print("/health:", json.dumps(h, ensure_ascii=False))
        c1 = requests.post(base + "/chat", json={"message": "hi"}, timeout=10).json()
        print("/chat1:", json.dumps({k: c1[k] for k in ("session_id", "reply")}, ensure_ascii=False))
        sid = c1["session_id"]
        c2 = requests.post(base + "/chat", json={"session_id": sid, "message": "推荐3只"}, timeout=30).json()
        print("/chat2:", "triggered", c2.get("tool_trace", {}).get("triggered_recommend"))
        r = requests.post(base + "/recommend", json={"universe": "symbols", "symbols": ["000001","000333","600519"]}, timeout=30).json()
        print("/recommend:", "picks", len(r.get("picks", [])))
        return 0
    except Exception as e:  # noqa: BLE001
        print("smoke failed:", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())

