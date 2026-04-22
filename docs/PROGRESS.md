# Current Progress

Last updated: 2026-04-22

## Snapshot

The repository has been reduced to the current service spine:

- `gateway/` exposes the FastAPI API
- `runtime/` owns the turn loop
- `memory/` stores session and transcript state
- `book/` builds the daybook and actionable board
- `judgment/` produces recommendation, follow-up, compare, and exit decisions
- `selection_engine/` remains the low-level ranking engine

## Recent Changes

### 2026-04-22

- Fixed stale backend CI references and synced the fix to GitHub.
- Removed the old `gp_assistant.chat` and `gp_assistant.recommend` compatibility surface.
- Deleted legacy tests that only existed to support retired service paths.
- Reduced the repository back to the current service architecture.
- Reorganized `docs/` so active docs stay at the top level and historical material is archived.

## Current State

- Main branch is aligned around the `gateway -> runtime -> judgment -> reply` flow.
- Legacy compatibility paths have been removed from production code.
- Service-related smoke and unit checks pass locally.
- Some runtime-generated files under `store/book/` still appear during local work and are treated as workspace artifacts, not documentation or source-of-truth code.

## Next Cleanup Candidates

- Review `tests/conftest.py` and further reduce historical ignore rules.
- Review `store/` tracking policy and decide which generated files should stay versioned.
- Normalize older docs that still contain encoding damage before keeping or deleting them.
