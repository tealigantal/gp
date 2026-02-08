"""Development bridge for src-layout.

This light bootstrap ensures `import gp_assistant` points to `src/gp_assistant`
without interfering with submodule imports. It mirrors attributes from the real
package and sets `__path__` to the src package directory so that
`python -m gp_assistant` resolves `src/gp_assistant/__main__.py`.
"""
from __future__ import annotations

import sys
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src" / "gp_assistant"
_INIT = _SRC / "__init__.py"

if _SRC.exists():
    # Make submodule discovery point at src/gp_assistant
    __path__ = [str(_SRC)]  # type: ignore[var-annotated]
    # Load the real __init__ to copy metadata and version
    try:
        spec = spec_from_file_location("_gp_assistant_src_init", _INIT)
        if spec and spec.loader:
            mod = module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            # propagate attributes into this package namespace
            for k, v in mod.__dict__.items():
                if not k.startswith("__") or k in {"__version__"}:
                    globals().setdefault(k, v)
            # set __file__ to src path for verification commands
            __file__ = str(_INIT)
    except Exception:
        # Best-effort; if src missing, leave module minimal
        pass

