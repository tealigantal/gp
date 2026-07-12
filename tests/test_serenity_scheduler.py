from datetime import datetime
from zoneinfo import ZoneInfo

from gp_assistant.serenity.scheduler import compute_schedule


def test_schedule_uses_elapsed_and_phase_floor():
    now = datetime(2026, 7, 10, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    fast = compute_schedule(last_elapsed_sec=0.2, completed_durations=[0.2, 0.3], now=now, is_trading_day=True)
    assert fast.delay_sec == 60
    slow = compute_schedule(last_elapsed_sec=50, completed_durations=[10, 20, 30], now=now, is_trading_day=True)
    assert slow.cost_sec == 50
    assert slow.delay_sec == 200


def test_schedule_backoff_and_circuit_breaker():
    now = datetime(2026, 7, 10, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    failed = compute_schedule(last_elapsed_sec=2, completed_durations=[2], now=now, consecutive_failures=3, is_trading_day=True)
    assert failed.delay_sec == 480
    limited = compute_schedule(last_elapsed_sec=2, completed_durations=[2], now=now, retry_after_sec=900, is_trading_day=True)
    assert limited.delay_sec == 900
    circuit = compute_schedule(last_elapsed_sec=2, completed_durations=[2], now=now, circuit_break=True, is_trading_day=True)
    assert circuit.delay_sec >= 1800


def test_backlog_uses_short_non_overlapping_catchup():
    now = datetime(2026, 7, 10, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    result = compute_schedule(last_elapsed_sec=7, completed_durations=[7], now=now, backlog=True, is_trading_day=True)
    assert result.delay_sec == 15
    assert result.stale_after_sec >= 120
