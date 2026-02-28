from __future__ import annotations

# Shim entry so that `python -m backtest.runner_weekly` works in src-layout repos.
from src.backtest.runner_weekly import *  # type: ignore

if __name__ == "__main__":  # pragma: no cover
    from src.backtest.runner_weekly import main

    main()

