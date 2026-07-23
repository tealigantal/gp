# Current Progress

Last updated: 2026-07-23

The contract-kernel hard cutover is implemented and locally validated. The configured development database now has canonical plan, runtime, publication, session, and turn records produced through the new-only path. The unified worker owns offline daily-evidence refresh, plan generation, and runtime refresh; it never runs from `/api/chat`.

The chat-first frontend has been rebuilt as a minimal responsive workspace against current publication, health, conversation, and chat contracts. Plain `docker compose up -d --build` now reproducibly builds the Windows-authored lockfile in Alpine, waits on API health, and starts healthy `gp`, `gp-worker`, and `web` services. Browser verification covered current candidates, a real LLM reply, saved-session reload, and zero captured console errors.

The frontend now tolerates minute-level runtime publication rollover without confusing it with a changed daily plan. Current and conversation-bound publications remain separate, health/publication reads are version-checked, unknown lineage fails closed without a false historical claim, reason codes render in Chinese, and candidate metrics use `进入评分` plus `execution_risk`. The deployed local web container passed a real follow-up on the previously affected `a7d44e66` session; backend services were not rebuilt or restarted.

Saved conversations now support confirmed permanent deletion from each sidebar card. Deletion is scoped to one session and its messages, cannot remove recommendation artifacts, cannot be undone by stale browser responses, and cannot be resurrected by a delayed same-ID chat request. The rebuilt local services passed an end-to-end disposable-session deletion; the eight pre-existing conversations remained intact.
