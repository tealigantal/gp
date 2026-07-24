# Deliberate Debt

None recorded for the contract-kernel cutover. The migration discards retired rows that cannot map exactly instead of introducing compatibility debt.

2026-07-24: Serenity v1 intentionally has no OCR path. Scanned, malformed, truncated, or otherwise unparsed relevant PDFs make the entire target batch 0% rather than guessing from metadata or applying partial coverage. This is safe but can reduce availability; adding a resource-bounded, auditable OCR lane remains future work and must preserve the same atomic batch gate.
