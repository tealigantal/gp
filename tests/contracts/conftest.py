from datetime import date, timedelta

import pytest

from gp_assistant.application.trading_calendar import CnATradingCalendar
from gp_assistant.contracts.market import TradingCalendarRef


@pytest.fixture(autouse=True)
def isolated_runtime_store(tmp_path, monkeypatch):
    """Worker preflight tests must never open the developer's live database."""
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("GP_CONTRACT_DB", str(tmp_path / "contracts.db"))


@pytest.fixture
def suspension_calendar():
    # Explicit fixture calendar, never a production weekday fallback. Includes
    # a long closure to prove that the engine consumes calendar membership.
    days = (date(2026, 7, 1) + timedelta(days=i) for i in range(130))
    return CnATradingCalendar(
        open_days=frozenset(day for day in days if day.weekday() < 5 and not date(2026, 10, 1) <= day <= date(2026, 10, 7)),
        ref=TradingCalendarRef(calendar_id="cn-a", revision="suspension-fixture", source="test-fixture"),
    )
