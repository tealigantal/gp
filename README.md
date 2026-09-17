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

### Docker runtime storage and proxies

`/app/store` is an explicitly initialized external Linux Docker volume named by `GP_RUNTIME_STORE_VOLUME` (default `gp-runtime-store`). Existing installations must stop `gp` and `gp-worker` before copying their store. `scripts/migrate_runtime_store.py` accepts read-only `/source`, an empty `/destination` volume and writable `/evidence`; it preserves originals, verifies every copied file SHA-256 and runs SQLite integrity checks before cutover. Do not run a local host worker against the retained Windows copy after migration: it is rollback evidence, not the active store. Read live artifacts through `docker compose exec -T gp ...`; make SQLite backups through its backup API, not by copying an active journal pair. Never delete the runtime volume as a rebuild step.

For a new empty installation, explicitly create `gp-runtime-store` before `docker compose up -d gp gp-worker web`. For migration, point `GP_RUNTIME_STORE_VOLUME` to the verified populated volume. Rollback requires stopping both writers and preserving/exporting new volume writes first; selecting an old directory without doing so discards later work. An image rollback requires a compatibility check against the committed-case reader and new policy. Preserve current volume writes before any coherent snapshot restoration; do not blindly run the old reader against staged new cases.

Host shell HTTP proxy variables are not Docker configuration. Optional `GP_BUILD_HTTP_PROXY`, `GP_BUILD_HTTPS_PROXY`, `GP_BUILD_ALL_PROXY` and corresponding `GP_RUNTIME_*` variables default empty. If needed use a container-reachable proxy such as `host.docker.internal`, not host loopback. Local API health checks bypass proxies.
