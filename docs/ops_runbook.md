# Ops Runbook

This runbook describes how to run and verify the current GP Assistant service.

## Scope

This document only covers the current service spine:

- API entry: `src/gp_assistant/gateway/`
- turn loop: `src/gp_assistant/runtime/turn_loop.py`
- market book refresh: `src/gp_assistant/book/`
- session and transcript storage: `src/gp_assistant/memory/`

It does not cover retired workbench, legacy chat adapters, or the removed compatibility surface.

## Prerequisites

- Python 3.11+
- Node.js 18+ for the frontend
- dependencies installed from `requirements.txt`

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
- `GET /api/session/{session_id}`
- `GET /api/sessions`
- `GET /api/run/{run_id}`
- `GET /api/side-results`

## Recommended Local Validation

Fast structural checks:

```bash
python -m compileall src
```

Service-facing tests:

```bash
python -m pytest -q tests/server/test_app_import.py tests/server/test_chat_endpoint_smoke.py
python -m pytest -q tests/test_api_smoke.py
python -m pytest -q tests/unit/test_interpret_request_types.py tests/unit/test_judgment_dispatch.py tests/unit/test_dispatch_new_handlers.py tests/unit/test_daybook_mapping.py
```

## Runtime Data

The repository writes runtime artifacts under `store/`.

Typical examples:

- `store/book/`
- `store/runs/`
- `store/portfolio/`
- `store/validation/`

These files are workspace artifacts. Treat them as generated state unless a specific file is intentionally versioned.

## Operational Notes

- The service is session-based. `session_id` is the stable handle for follow-up turns.
- `run_id` is the stable handle for a published recommendation result.
- `book/current.json` is runtime state, not the primary source code contract.
- Freshness behavior is defined in [data_freshness_policy.md](./data_freshness_policy.md).

## When Something Looks Wrong

1. Check `/api/health`.
2. Run `python -m compileall src`.
3. Run the server smoke tests listed above.
4. Inspect `store/book/current.json` only as a debug artifact, not as a design reference.
5. Use [PROGRESS.md](./PROGRESS.md) and [../src/gp_assistant/ARCHITECTURE.md](../src/gp_assistant/ARCHITECTURE.md) as the current structural references.
