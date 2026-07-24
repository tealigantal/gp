# Architecture Decision Records

Create an ADR when work changes module or data ownership, public interfaces, trust/security boundaries, persistence strategy, deployment topology, major dependencies, or long-term compatibility.

Each ADR records Status, Context, Considered Options, Decision, Rationale, Consequences, Migration, Rollback, and Date.

## Index

- [0001 — Serenity Alpha experimental add-on](./0001-serenity-alpha-experimental-addon.md)
- [0004 — Serenity resident reference service](./0004-serenity-resident-reference-service.md) — topology retained; reference-only authority superseded by 0005
- [0002 — Canonical current recommendation bundle](./0002-canonical-current-recommendation-bundle.md)
- [0003 — Explicit market time and read-only SQLite](./0003-market-time-and-readonly-sqlite.md)
- [0005 — Serenity native Alpha and real-LLM chat](./0005-serenity-native-alpha-and-real-llm-chat.md)
- [0006 — Single assistant-turn presentation contract](./0006-assistant-turn-presentation-contract.md)
- [0007 — Runtime contract consolidation](./0007-runtime-contract-consolidation.md)
- [0008 — Full-market universe ownership and additive Serenity](./0008-full-market-universe-and-additive-serenity.md)
- [0010 — Serenity fixed 3% and unified worker isolation](./0010-serenity-fixed-three-percent-unified-worker.md) — supersedes the former 0%-8% promotion range and separate-container topology
- [0011 — Lunch Top-30 five-minute rerank](./0011-lunch-top30-five-minute-rerank.md) — adds an immutable 11:30 plan version without changing schema or HTTP shapes
- [0012 — Exact daily coverage and bounded Serenity OCR](./0012-daily-coverage-and-serenity-ocr.md) — requires exact-date readiness and adds fail-closed Chinese OCR without schema or HTTP changes
