from __future__ import annotations

from typing import List

from ..providers.universe_provider import UniverseProvider


def load_universe_symbols() -> List[str]:
    return UniverseProvider().get_symbols()
