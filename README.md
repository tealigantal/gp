# GP

GP is a chat-first A-share main-board decision assistant for short 1–3 trading-day plans.

## One-command local workspace

```powershell
docker compose up -d --build
```

Open `http://127.0.0.1:8080`. The command builds and starts the API, recommendation worker, and chat frontend; Compose waits for the API health check before starting its dependants. A local `.env` is optional for container startup, but a valid `LLM_API_KEY` is required for real narrated chat replies.

The frontend is deliberately chat-first: saved conversations on the left, the canonical conversation in the center, and the current immutable recommendation publication on the right. It never ranks candidates or derives recommendation facts in the browser.

Its only recommendation lifecycle is:

`RecommendationPlan` → optional `RuntimeObservation` → `RecommendationPublication`

At 11:30 the worker may append a new immutable plan that reranks only the morning plan's frozen Top-30 from one complete five-minute batch. It never rewrites the morning plan or changes the public lifecycle; incomplete lunch data leaves the morning publication current.

Read the [documentation map](docs/README.md) first. Before changing the recommendation path, read [current contracts](docs/contracts/CURRENT_CONTRACTS.md), [retirement record](docs/contracts/RETIRED_CONTRACTS.md), and the [registry](docs/contracts/registry.yaml).

## Commands

```powershell
$env:PYTHONPATH = 'src'
python -m gp_assistant serve --host 127.0.0.1 --port 8000
python -m gp_assistant.cli refresh-daily
python -m gp_assistant.cli worker
python -m pytest -q
python -m gp_assistant.contracts.manifest --check
python -m gp_assistant.contracts.check_retired
```

The public recommendation read is `GET /api/recommendation/current`. A missing or insufficient-evidence result is explicit; it never reads a retired structure.

`migrate-contracts` is retained only for an explicitly identified pre-contract legacy database after all writers are stopped. It refuses a `contract_kernel.v1` database; never run it against the current `store/agent.db` as a routine startup or repair command.
