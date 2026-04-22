# GP Assistant

Chat-first A-share research and recommendation service built around a single runtime spine:

- `gateway/` exposes the FastAPI API
- `runtime/` owns the turn loop
- `memory/` stores session and transcript state
- `book/` builds the market book and actionable board
- `judgment/` produces recommendation, follow-up, compare, and exit decisions
- `selection_engine/` remains the low-level ranking engine

## Current Status

The repository has been cleaned back to the current service architecture.

- legacy `gp_assistant.chat` compatibility code removed
- legacy `gp_assistant.recommend` compatibility code removed
- retired test surfaces removed
- docs reorganized into active docs and archive

Latest progress is tracked in [docs/PROGRESS.md](./docs/PROGRESS.md).

## Quick Start

### Backend

Requirements:

- Python 3.11+

Setup:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Run the API:

```bash
set PYTHONPATH=src
python -m gp_assistant serve --host 127.0.0.1 --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/api/health
```

Single-turn local chat:

```bash
set PYTHONPATH=src
python -m gp_assistant chat "给我三只当前可看的票"
```

### Frontend

Requirements:

- Node.js 18+

Run:

```bash
cd frontend
npm ci
npm run dev
```

Default frontend URL:

- `http://localhost:5173`

## Main Endpoints

- `POST /api/chat`
- `GET /api/health`
- `GET /api/book/current`
- `GET /api/session/{session_id}`
- `GET /api/sessions`
- `GET /api/run/{run_id}`
- `GET /api/side-results`

## Repository Layout

```text
src/gp_assistant/
  gateway/          FastAPI entrypoints
  runtime/          turn loop and freshness handling
  memory/           session, transcript, claim storage
  book/             daybook and board construction
  judgment/         user-facing decision layer
  evidence/         market / portfolio / validation services
  selection_engine/ ranking and recommendation internals
  strategy/         strategy library and scoring logic
```

## Validation

Useful local checks:

```bash
python -m compileall src
python -m pytest -q tests/server/test_app_import.py tests/server/test_chat_endpoint_smoke.py
python -m pytest -q tests/unit/test_interpret_request_types.py tests/unit/test_judgment_dispatch.py tests/unit/test_dispatch_new_handlers.py tests/unit/test_daybook_mapping.py
python -m pytest -q tests/test_api_smoke.py
```

## Docs

- [docs/README.md](./docs/README.md)
- [docs/PROGRESS.md](./docs/PROGRESS.md)
- [docs/ops_runbook.md](./docs/ops_runbook.md)
- [docs/data_freshness_policy.md](./docs/data_freshness_policy.md)
- [docs/service_contract.md](./docs/service_contract.md)

## Notes

- Runtime-generated files under `store/` are workspace artifacts, not core source files.
- Some archived docs still contain historical encoding damage; they were kept for traceability, not as current documentation.
