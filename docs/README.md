# Docs Index

This folder is split into:

- current docs: documents that describe the repository as it exists now
- archive: historical plans, work summaries, and retired acceptance notes

## Current

- [PROGRESS.md](./PROGRESS.md)
  Latest project status, Market-Memory production path, and validation snapshot.
- [ops_runbook.md](./ops_runbook.md)
  Operational notes, Docker commands, validation commands, and routine checks.
- [data_freshness_policy.md](./data_freshness_policy.md)
  Freshness rules for daybook and session reuse. Some historical pulse notes may remain as archived context, not production behavior.
- [service_contract.md](./service_contract.md)
  Output contract notes for chat responses, recommendation artifacts, `DecisionContextModel`, thesis lifecycle, decision synthesis, and `DecisionContextSnapshot`.
- [historical_validation.md](./historical_validation.md)
  Historical Replay, Legacy-vs-New AB validation, calibration, no-trade tracking, and current local replay results.

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
- The current production decision path is `Market Data -> Signal Engine -> Market Memory -> Probability Engine -> Risk Engine -> Decision Intelligence -> Thesis Lifecycle -> Decision Synthesizer`.
- `src/gp_assistant/selection_engine/` is retained as legacy reference and low-level market-data support, not as the production ranking authority.
- Legacy `gp_assistant.chat` and `gp_assistant.recommend` compatibility surfaces were removed on April 22, 2026.
