from __future__ import annotations

from typing import Final, Literal, TypeAlias, cast


# The only operations accepted by the resident recommendation runtime.
# Each value has a distinct lifecycle meaning; retired replay/daily aliases
# are deliberately absent so callers cannot silently take an obsolete path.
RuntimeOperation: TypeAlias = Literal[
    "auto",
    "rebuild_daybook",
    "postclose_archive",
]

RUNTIME_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "auto",
        "rebuild_daybook",
        "postclose_archive",
    }
)


def require_runtime_operation(value: object) -> RuntimeOperation:
    operation = str(value or "").strip()
    if operation not in RUNTIME_OPERATIONS:
        raise ValueError(f"runtime_operation_invalid:{operation or 'missing'}")
    return cast(RuntimeOperation, operation)
