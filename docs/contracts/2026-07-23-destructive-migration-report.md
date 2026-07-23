# 2026-07-23 Destructive Migration Report

The configured development database was atomically replaced after stopped-writer verification, temporary backup creation, schema validation, foreign-key validation, integrity validation, and canonical-startup smoke.

Pre-cutover inventory: 1,663 `recommendation_snapshots`, 1 `current_snapshot`, 170 `daybook_versions`, 45 sessions, 164 turns, and 248 claims.

Migrated rows: 0. Discarded rows: 1,663 recommendation records plus their dependent pointer, session, turn, claim, and daily-container records. Reason: no source row contained a complete exact `RecommendationPlan` plus optional `RuntimeObservation` plus `RecommendationPublication` envelope. The migration does not guess identities, sessions, timestamps, or runtime evidence.

The active database now contains only `schema_metadata`, `recommendation_plans`, `runtime_observations`, `recommendation_publications`, `current_publication`, `sessions`, `turns`, and `claims`. The temporary backup was removed after successful replacement.
