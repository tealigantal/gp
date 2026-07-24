# Validation Ledger

## Lunch Top-30 Five-Minute Rerank

2026-07-24: `python -m pytest -q` passed 40 tests. The suite covers the exact 11:32 trigger, complete 30-symbol plus CSI300 batch gating, missing/duplicate/unfinished source failure, deterministic reranking, unchanged daily trade facts, Serenity's persisted fixed 3% bound, append-only plan/runtime/publication history, current-pointer CAS, late-publication prevention, real spawned-process write exclusion, current-schema migration refusal without byte changes, old/new conversation publication binding, afternoon preservation of the immutable lunch signal, product-only LLM context and output rejection when engineering identifiers or interfaces leak.

2026-07-24: `python -m pytest -q tests/test_akshare_minute_provider.py` passed 3 tests. `python -m pytest -q tests/integration/test_live_lunch_min5_source.py -m integration` passed 1 live read-only test through the isolated child-process collector. The live batch contained all 30 frozen candidates plus CSI300 with exactly 24 closed five-minute rows from 09:35 through 11:30.

2026-07-24: `python -m compileall -q src tests`, contract-manifest check, retired-symbol check, `docker compose config --quiet`, and `git diff --check` passed. Tests used temporary SQLite files; no production database, container, public response field, ContractModel, or schema version was changed or deployed.

2026-07-24: A final SQLite read-only compatibility audit of the live `contract_kernel.v1` store found zero content-ID, publication-decision, lineage, candidate, plan/runtime market-session, current-pointer, or foreign-key problems; `integrity_check` returned `ok`. This specifically confirmed that the PR retains the existing v1 publication reason semantics instead of silently invalidating historical rows.

## Serenity Fixed 3% Unified Worker

2026-07-24: `compileall`, the full 18-test contract suite, retired-symbol enforcement, Compose config, and diff checks passed. Tests prove positive, negative, and neutral complete-batch behavior; exact zero invariance when one symbol is missing or a source fails; the ±0.03 cap; stable zero-plan reuse and complete-batch plan invalidation; full evaluated-candidate retention with Serenity restricted to the frozen Top-30; prevention of uncovered candidates entering selection because a covered finalist was penalized; first-seen availability that never backdates evidence to the announcement clock; product-level public health without raw collector errors; and product-only LLM context without Serenity internal references.

2026-07-24: Rebuilt `gp-backend:local` and recreated `gp` and `gp-worker` from the same image `sha256:c10be816d0671792fcdb27d94ad7e8720af4cf8737750ad4c5471e4509f3aa41`. Container/local SHA-256 matched for both the Serenity service and conversation prompt. API health was healthy, the unified worker had separate core and Serenity processes, and the former `gp-gp-serenity-worker-1` container was removed by exact name. The historical 8.6 MB Serenity evidence database remained present.

2026-07-24: A live official-announcement poll built the current Top-30 target and encountered an unparsed `000100` PDF. Health exposed Serenity degradation, the committed recommendation used `adaptive_kernel_v3_serenity`, all 30 candidate Serenity weights were exactly 0, and the core worker subsequently published a new runtime/publication. A real chat explained the fixed 3%, signed bound, neutral complete case, and source-failure whole-batch zero in natural Chinese without exposing fields, reason codes, IDs, or interfaces; the disposable verification conversation was then deleted.

## Contract Kernel

2026-07-23: backend suite passed (5 tests); `compileall`, manifest, retirement, and diff checks passed. Frontend lint, typecheck, test (1 test), and production build passed.

The real local data path generated a 2026-07-23 plan from a live AkShare spot universe (3,194 main-board symbols) intersected with cached daily evidence (3,193 covered symbols, 2026-07-22). It evaluated 197 candidates and deterministically selected 3. A real `/api/chat` call completed through the configured LLM; a same-session/client-turn retry returned the persisted response without a duplicate turn. Outside market hours, the actual runtime refresh explicitly published `market_not_in_trading_phase` and `tradeable_now=false`.

The configured development database passed `integrity_check`, `foreign_key_check`, canonical initialization, and API health smoke after destructive replacement.

## Workspace Reconnection

2026-07-23: Restored the chat-first workspace against the current Contract Kernel. Added read-only canonical conversation list/detail routes; `tests/contracts` passed (6 tests), including an HTTP verification that a persisted session returns ordered canonical turns. Frontend `typecheck`, `lint`, test (1 test), and production build passed before container rebuild.

2026-07-23: Rebuilt the local Compose `gp`, `gp-worker`, and `web` services. Browser verification at `http://127.0.0.1:8080` showed the restored workspace, current candidate snapshot, session switching, persisted-turn reload, and a real LLM response correctly describing post-close state and 2026-07-22 daily evidence. No browser console errors were observed. A stale bind-mounted history lock from a replaced container was automatically reclaimed by the rebuilt worker; the expanded contract suite passed (7 tests) and no later worker lock timeout appeared.

## Chat Agent Showcase UI

2026-07-23: Recreated the missing frontend against current contracts and passed `npm run typecheck`, `npm run lint`, `npm test -- --run` (6 tests), and `npm run build`. The final production build emitted 155.57 kB JavaScript and 16.31 kB CSS before gzip. Cross-platform optional bindings for Rollup and SWC are explicitly locked so the Windows-generated lockfile builds reproducibly in the Alpine image. Tests cover canonical fact rendering, chat persistence, historical-publication isolation, state-sync failure closure, response-loss retry with stable session and client-turn identities, and Chinese IME composition.

2026-07-23: `docker compose config --quiet` passed. Plain `docker compose up -d --build` built the API and web images, then started `gp` healthy, `gp-worker` running, and `web` healthy. HTTP verification through `http://127.0.0.1:8080` returned 200 and proxied a current publication with 2026-07-23 daily evidence in post-close phase.

2026-07-23: Automated browser verification found 901 characters of meaningful initial content, no Vite error overlay, and no captured console errors. It rendered six saved conversations, three current selected candidates in engine order, and the post-close unavailable state. A new real chat produced and persisted a two-turn conversation; after page reload, selecting the newest saved session restored both ordered turns. The frontend exposed three candidate cards and two conversation messages after reload.

2026-07-23: After independent frontend review, historical sessions now hide the unrelated current decision brief, polling failure forces execution unavailable, uncertain retries reuse the original client-turn identity, IME composition Enter does not submit, and mobile history remains horizontally accessible. The final web-only rebuild used `docker compose up -d --no-deps --build web`; it did not rebuild or restart backend services. At a 390 px browser viewport, all six history buttons remained visible through the horizontal session rail. The final browser pass again found no console error or framework overlay.

2026-07-23: Repaired false historical-session detection caused by minute-level runtime publication churn. Frontend lint, typecheck, 10 Vitest cases, production build, and diff checks passed. The tests cover same-plan publication rollover, crossed health/publication reads, conversation request ordering, current/publication separation, Chinese reason rendering, evaluated-count wording, and execution-risk semantics. A web-only Compose rebuild left `gp` and `gp-worker` untouched. Browser verification reopened the reported `a7d44e66` session, correctly labeled its initially unknown lineage, sent a real follow-up, learned the trusted same-plan binding, restored all three current candidates, rendered `进入评分 198`, `执行风险`, and the Chinese next-session reason, and found no console errors or framework overlay.

2026-07-23: Added per-conversation deletion and passed backend compile, the full 8-test backend suite, frontend lint/typecheck, 14 Vitest cases, production build, Compose config, and diff checks. Tests cover exact session deletion, cascaded turn removal, preservation of another session and current plan/publication, tombstoned late-chat rejection, confirmation cancellation, active/inactive deletion, stale list suppression, and both deletion/switch response orders. Rebuilt `gp`, `gp-worker`, and `web`; all became healthy/running. Browser verification created only `session_delete_e2e_1784815569461`, deleted it through the first card's UI control, observed the list count move from 9 to 8, reloaded with the card still absent, received 404 from its conversation read and 409 `conversation_deleted` from a late same-ID chat, and captured no console error or framework overlay. No pre-existing user conversation was deleted.
