from __future__ import annotations

from src.gp_assistant.observe.degrade import record


def test_warn_not_degrade():
    dbg = {}
    record(dbg, "X", {}, severity="warn")
    assert not dbg.get("degraded", False)
    assert "degrade_reasons" not in dbg or not dbg.get("degrade_reasons")
    assert isinstance(dbg.get("warnings"), list)
    assert dbg["warnings"][0]["reason_code"] == "X"

