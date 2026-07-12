# GP ExecPlan Contract

Every active ExecPlan must be self-contained, outcome-focused, repository-specific, milestone-based, independently verifiable, safe to resume, and explicit about rollback and idempotence.

Each plan must maintain these sections throughout execution:

- Purpose / Big Picture
- Progress
- Surprises & Discoveries
- Decision Log
- Outcomes & Retrospective
- Context and Orientation
- Plan of Work
- Concrete Steps
- Validation and Acceptance
- Idempotence and Recovery
- Artifacts and Notes
- Interfaces and Dependencies

Progress entries must include dates and observed facts. Validation entries must distinguish planned checks from commands actually executed. A plan is not complete merely because code compiles; it must record the user-visible result, remaining risks, and rollback behavior.
