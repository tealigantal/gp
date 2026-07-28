# Documentation Map

This directory is the navigation entry point for GP documentation. Current
product and engineering decisions take precedence over archived material.
Before changing the recommendation path, read the current contract kernel and
its registry.

## Current sources of truth

| Topic | Canonical document |
| --- | --- |
| Product outcome and approval gates | [../PROJECT_GOAL.md](../PROJECT_GOAL.md) |
| Repository operating boundaries and verified commands | [../AGENTS.md](../AGENTS.md) |
| Active contract lifecycle | [contracts/CURRENT_CONTRACTS.md](contracts/CURRENT_CONTRACTS.md) |
| Retired names that must not return | [contracts/RETIRED_CONTRACTS.md](contracts/RETIRED_CONTRACTS.md) |
| Typed contract registry | [contracts/registry.yaml](contracts/registry.yaml) |
| User journey and presentation semantics | [PRODUCT.md](PRODUCT.md) |
| Runtime ownership and topology | [ARCHITECTURE.md](ARCHITECTURE.md) and [../src/gp_assistant/ARCHITECTURE.md](../src/gp_assistant/ARCHITECTURE.md) |
| HTTP/domain surface | [service_contract.md](service_contract.md) |
| Freshness and trading-time rules | [data_freshness_policy.md](data_freshness_policy.md) |
| Historical replay method | [historical_validation.md](historical_validation.md) |
| Executed verification evidence | [VALIDATION.md](VALIDATION.md) |
| Recoverable project state | [PROGRESS.md](PROGRESS.md) |
| Research evidence and deliberate compromises | [RESEARCH_LOG.md](RESEARCH_LOG.md) and [DEBT.md](DEBT.md) |

## Active and completed execution plans

Plans retain their outcome and evidence; they are not replacement contracts.

| Plan | Status |
| --- | --- |
| [2026-07-24 daily refresh and Serenity OCR recovery](plans/2026-07-24-daily-refresh-and-serenity-ocr-recovery.md) | Implemented and locally deployed; records the remaining historical release context. |
| [2026-07-24 lunch Top-30 five-minute rerank](plans/2026-07-24-lunch-five-minute-rerank.md) | Implemented and locally validated; its stated review status is historical. |
| [2026-07-24 Serenity fixed 3% unified worker](plans/2026-07-24-serenity-fixed-three-percent-worker.md) | Implemented and locally deployed. |
| [2026-07-28 official suspension evidence](plans/2026-07-28-official-suspension-evidence.md) | Implemented and worker-verified against the real remaining daily-coverage residue. |
| [2026-07-23 chat-agent showcase UI](plans/2026-07-23-chat-agent-showcase-ui.md) | Completed historical implementation record. |
| [2026-07-23 frontend workspace reconnection](plans/2026-07-23-frontend-workspace-reconnection.md) | Completed historical implementation record. |
| [2026-07-23 contract-kernel hard cutover](plans/2026-07-23-contract-kernel-hard-cutover.md) | Completed destructive migration record; do not repeat against the current store. |
| [2026-07-13 Serenity resident service](plans/2026-07-13-serenity-resident-service.md) | Superseded by ADR 0010's unified-worker topology. |
| [2026-07-11 Serenity Alpha](plans/2026-07-11-serenity-alpha.md) | Superseded historical experiment record. |

## Decision and change records

- [Architecture Decision Records](adr/README.md) indexes all retained ADRs and
  identifies superseded decisions.
- [Contract kernel hard-cutover change record](contracts/changes/2026-07-23-contract-kernel-hard-cutover.md)
  and its [migration report](contracts/2026-07-23-destructive-migration-report.md)
  are historical, destructive-cutover evidence.
- [Contract-change template](contracts/changes/TEMPLATE.md) is the format for a
  future approved contract change; it is not a current contract.

## Historical archive

[archive/README.md](archive/README.md) lists every archived work summary,
manual acceptance record, and retired plan. Archived material is traceability
evidence only and must not be used to infer the current runtime path.
