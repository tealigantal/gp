# Docs Index

This folder is split into:

- current docs: documents that describe the repository as it exists now
- archive: historical plans, work summaries, and retired acceptance notes

## Current

- [PROGRESS.md](./PROGRESS.md)
  Latest project status, daily-plan runtime status, derived mainline behavior, and validation snapshot.
- [ops_runbook.md](./ops_runbook.md)
  Operational notes and routine commands.
- [data_freshness_policy.md](./data_freshness_policy.md)
  Freshness rules for daybook and session reuse. Some historical pulse notes may remain as archived context, not production behavior.
- [service_contract.md](./service_contract.md)
  Output contract notes for recommendation artifacts.

## Archive

- [archive/history/](./archive/history/)
  Work summaries and one-off implementation notes.
- [archive/plans/](./archive/plans/)
  Refactor plans and task-oriented design notes.
- [archive/manual-acceptance/](./archive/manual-acceptance/)
  Retired manual acceptance steps for removed surfaces.

## Notes

- The current service entrypoint is `src/gp_assistant/gateway/`.
- The current turn loop is `src/gp_assistant/runtime/turn_loop.py`.
- Legacy `gp_assistant.chat` and `gp_assistant.recommend` compatibility surfaces were removed on April 22, 2026.
