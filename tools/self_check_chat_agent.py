from __future__ import annotations

"""
Chat agent self-check.

Runs a minimal flow using FastAPI TestClient:
- Recommend (service/latest)
- Follow-up analysis (K-line)
- Ask for second symbol
- Why recommended

Prints pass/fail with reasons.
"""

import json
from typing import Any, Dict

from fastapi.testclient import TestClient

from gp_assistant.server.app import app
from gp_assistant.chat import session_store as store


def _ok(cond: bool) -> str:
    return "PASS" if cond else "FAIL"


def main() -> None:  # noqa: D401
    c = TestClient(app)
    results: Dict[str, Any] = {}

    # 1) recommend via service
    r1 = c.post("/api/chat", json={"message": "latest recommend 3"})
    j1 = r1.json()
    sid = j1.get("session_id")
    results["recommend"] = {"status": _ok(bool(sid) and bool(j1.get("reply"))), "detail": j1}

    # Seed last_recommend_symbols if missing to enable deterministic follow-ups
    try:
        syms = (j1.get("tool_trace") or {}).get("recommend_result", {}).get("picks", [])
        syms = [p.get("symbol") for p in syms if isinstance(p, dict)]
    except Exception:
        syms = []
    if not syms:
        store.update_state(sid, {"last_recommend_symbols": ["600519", "000333", "000001"]})

    # 2) kline analysis (default first)
    r2 = c.post("/api/chat", json={"session_id": sid, "message": "研究K线 给出合理的买卖点"})
    j2 = r2.json()
    results["analyze_first"] = {
        "status": _ok(bool(j2.get("reply"))),
        "detail": j2,
    }

    # 3) second symbol
    r3 = c.post("/api/chat", json={"session_id": sid, "message": "第二只"})
    j3 = r3.json()
    # Verify focus updated
    st = store.get_state(sid)
    results["second_symbol"] = {
        "status": _ok(bool(j3.get("reply")) and bool(st.get("current_focus_symbol"))),
        "detail": j3,
    }

    # 4) why recommended
    r4 = c.post("/api/chat", json={"session_id": sid, "message": "为什么推荐它"})
    j4 = r4.json()
    results["why"] = {"status": _ok(bool(j4.get("reply"))), "detail": j4}

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
