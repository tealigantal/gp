# Ops Runbook

This runbook describes how to run and verify the current GP Assistant service.

## Scope

This document covers the current service spine:

- API entry: `src/gp_assistant/gateway/`
- turn loop: `src/gp_assistant/runtime/turn_loop.py`
- LLM intent routing: `src/gp_assistant/llm/interpret.py`
- market book refresh: `src/gp_assistant/book/`
- session and transcript storage: `src/gp_assistant/memory/`
- cross-cutting service facade: `src/gp_assistant/kernel/`

It does not cover legacy chat adapters or the removed compatibility surface.

## Prerequisites

- Python 3.11+
- Node.js 18+ for the frontend
- dependencies installed from `requirements.txt`
- an LLM configuration for `/api/chat` intent parsing

Backend setup:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Frontend setup:

```bash
cd frontend
npm ci
```

## Run Locally

### Start the API

```bash
set PYTHONPATH=src
python -m gp_assistant serve --host 127.0.0.1 --port 8000
```

### Start the frontend

```bash
cd frontend
npm run dev
```

### Single-turn local execution

```bash
set PYTHONPATH=src
python -m gp_assistant chat "给我三只当前可看的票"
```

### Refresh the market book once

```bash
set PYTHONPATH=src
python -m gp_assistant pulse
```

## Main Runtime Checks

Health:

```bash
curl http://127.0.0.1:8000/api/health
```

Core endpoints:

- `POST /api/chat`
- `GET /api/health`
- `GET /api/book/current`
- `GET /api/book/slot/{artifact_id}`
- `GET /api/session/{session_id}`
- `GET /api/sessions`
- `GET /api/run/{run_id}`
- `GET /api/recommend_v2`
- `POST /api/compare`
- `GET /api/pick`
- `GET /api/validation/summary`
- `GET /api/workbench`
- `GET /api/side-results`

Chat intent parsing is an explicit LLM dependency:

- LLM unavailable returns HTTP 503 with `LLM 意图解析服务不可用`
- invalid or semantically inconsistent LLM TurnFrame after one repair attempt returns HTTP 502 with `LLM 意图解析返回无效结果`
- the service should not silently fall back to a fake chat intent for market requests

## Recommended Local Validation

Fast structural checks:

```bash
python -m compileall -q src
```

Service-facing tests:

```bash
python -m pytest -q tests/server/test_app_import.py tests/server/test_chat_endpoint_smoke.py
python -m pytest -q tests/test_api_smoke.py
python -m pytest -q tests/unit/test_interpret_request_types.py tests/unit/test_judgment_dispatch.py tests/unit/test_dispatch_new_handlers.py tests/unit/test_daybook_mapping.py
python -m pytest -q tests/kernel/test_kernel_facade_smoke.py tests/test_term_explain_flow.py
```

Default backend suite:

```bash
python -m pytest -q
```

## Runtime Data

The repository writes runtime artifacts under `store/`.

Typical examples:

- `store/book/`
- `store/runs/`
- `store/recommend/`
- `store/portfolio/`
- `store/validation/`

These files are workspace artifacts. Treat them as generated state unless a specific file is intentionally versioned.

`store/book/`, `store/runs/`, and most generated recommendation artifacts should stay out of version control.

## Operational Notes

- The service is session-based. `session_id` is the stable handle for follow-up turns.
- `run_id` is the stable handle for a published recommendation result.
- `book/current.json` is runtime state, not the primary source code contract.
- Freshness behavior is defined in [data_freshness_policy.md](./data_freshness_policy.md).
- `kernel.facade` is the active service boundary for recommendation v2, compare, pick detail, validation summary, portfolio state, execution preview, paper execution, and workbench aggregation.

## When Something Looks Wrong

1. Check `/api/health`, especially `llm_ready`, `runtime.book_freshness`, and provider status.
2. Run `python -m compileall -q src`.
3. Run the server smoke tests listed above.
4. If `/api/chat` returns 503, fix LLM configuration before debugging judgment logic.
5. If `/api/chat` returns 502, inspect the intent parser raw-output detail and router prompt contract.
6. Inspect `store/book/current.json` only as a debug artifact, not as a design reference.
7. Use [PROGRESS.md](./PROGRESS.md) and [../src/gp_assistant/ARCHITECTURE.md](../src/gp_assistant/ARCHITECTURE.md) as the current structural references.
