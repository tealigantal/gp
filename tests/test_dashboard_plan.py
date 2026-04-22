from datetime import datetime

from gp_assistant.runtime.freshness_policy import make_dashboard_refresh_plan


def test_make_dashboard_refresh_plan_intraday_l1():
    plan = make_dashboard_refresh_plan(now=datetime(2024, 3, 20, 10, 0))
    assert plan.level == 'L1'
    assert plan.scope == 'watchset'
    assert plan.target_pulse_trade_day is not None


def test_make_dashboard_refresh_plan_nontrading_l2():
    # Saturday
    plan = make_dashboard_refresh_plan(now=datetime(2024, 3, 23, 10, 0))
    assert plan.level == 'L2'
    assert plan.scope == 'watchset'
