# Contract Kernel Hard Cutover

The contract kernel replaces distributed recommendation structures with immutable plan, runtime-observation, and publication aggregates. It is a destructive, non-compatible change. The schema manifest and retirement checker are mandatory acceptance gates. Rollback is Git-level before the one-time database replacement; normal runtime never rolls back to a retired schema.
