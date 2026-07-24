# Markdown Documentation Consolidation ExecPlan

## Purpose / Big Picture

Make the tracked Markdown corpus navigable without rewriting historical evidence or changing the recommendation contract. The outcome is one current documentation map, complete ADR and archive indexes, valid local Markdown navigation, and a record of this documentation-only validation.

## Progress

- [x] 2026-07-24: Classified GP as an initialized important project and this as a repository-wide documentation-maintenance task.
- [x] 2026-07-24: Inventoried 47 tracked Markdown files outside ignored runtime artifacts and identified stale index targets in the ADR and archive indexes.
- [x] 2026-07-24: Added the current documentation map; repaired ADR and archive navigation without deleting or rewriting historical records.
- [x] 2026-07-24: Ran local-link, whitespace, and repository-state validation; updated the validation ledger and progress record; prepared the documentation-only change for commit and push to `main`.

## Surprises & Discoveries

- The previous ADR index named four absent records (0002, 0003, 0005, and 0007) and omitted the retained ADR 0009.
- The archive notice linked to a nonexistent `docs/ops_runbook.md`; its `../README.md` link also resolved to the missing `docs/README.md` before this consolidation.

## Decision Log

- 2026-07-24: Preserve dated plans, acceptance records, summaries, and repair briefs as historical evidence rather than deleting or silently modernizing their claims.
- 2026-07-24: Use `docs/README.md` as a navigation index, not a competing contract. `docs/contracts/CURRENT_CONTRACTS.md` remains the recommendation contract authority.

## Outcomes & Retrospective

The Markdown inventory found no broken relative links after consolidation. `git diff --check` passed. The documentation-only diff is ready to be committed and pushed to the user requested remote `main` branch.

## Context and Orientation

The current recommendation path is governed by `docs/contracts/`, while project state and executed evidence live in the top-level documents under `docs/`. `docs/archive/` is explicitly historical. Runtime artifacts under `store/`, `cache/`, and `results/` are out of scope and must not be staged.

## Plan of Work

1. Inventory Markdown paths and identify each document's current, historical, or template role.
2. Repair only navigational/document-status drift and add a single map.
3. Validate local Markdown links and repository whitespace.
4. Record actual results, review the diff, then commit and push to `main`.

## Concrete Steps

- Use `rg --files -g '*.md'` excluding runtime artifacts for inventory.
- Check Markdown links against local paths and use `git diff --check`.
- Do not alter application code, contracts, runtime data, or historical evidence beyond clearly labeling/indexing its role.

## Validation and Acceptance

- Every tracked Markdown file is reachable from an appropriate index or remains a documented root/project-control file.
- No local Markdown link points to a missing file.
- `git diff --check` passes and the staged change contains Markdown only.

## Idempotence and Recovery

Re-running the inventory and link check is read-only. The added indexes can be updated incrementally as new documents are created. Reverting this documentation-only commit restores prior navigation without changing product or runtime state.

## Artifacts and Notes

- Current map: `docs/README.md`
- ADR index: `docs/adr/README.md`
- Archive index: `docs/archive/README.md`

## Interfaces and Dependencies

No public interface, dependency, schema, container, or runtime artifact is changed.
