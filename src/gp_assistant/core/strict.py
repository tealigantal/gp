from __future__ import annotations

import os


def is_strict() -> bool:
    """Return True when strict output mode is enabled.

    Strict mode is enabled by default; set GP_STRICT_OUTPUT=0 to disable.
    """
    return os.getenv("GP_STRICT_OUTPUT", "1").strip() not in {"0", "false", "False"}

