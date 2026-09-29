import json
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import pytest
import requests

from gp_assistant.application.entry_service import EntryService
from gp_assistant.application.conversation_service import ConversationService
from gp_assistant.application.publication_service import PublicationService
from gp_assistant.contracts.entry import EntryJudgment
from gp_assistant.intraday.entry_evidence import build_evidence, normalize
from gp_assistant.providers.sina_minutes import MinuteDataError
from gp_assistant.store import ContractStore
from .test_contract_lifecycle import plan, TZ


def clock(hour=14, minute=40, day=23):
    return datetime(2026, 7, day, hour, minute, tzinfo=TZ)


def bars(end="15:00", closes=None):
    stamps = list(pd.date_range("2026-07-23 09:35", "2026-07-23 11:30", freq="5min")) + list(pd.date_range("2026-07-23 13:05", f"2026-07-23 {end}", freq="5min"))
    prices = np.linspace(10.1, 10.7, len(stamps))
    if closes is not None:
        prices[-len(closes):] = closes
    return pd.DataFrame({"trade_time": stamps, "open": prices, "close": prices, "high": prices + .02, "low": prices - .02, "vol": 1000., "amount": prices * 1000})


class Model:
    def __init__(self, action="consider_entry", trend="strengthening"):
        self.calls = []
        self.action, self.trend = action, trend

    def chat(self, messages, **kwargs):
        self.calls.append(json.loads(messages[-1]["content"]))
        judgment = EntryJudgment(action=self.action, trend=self.trend, conclusion="依据近期证据形成的测试判断", reasons=("近期价格结构",), evidence_fields=("return_30m", "entry_position"), change="新证据已更新" if self.calls[-1]["previous"] else "")
        return {"choices": [{"message": {"content": judgment.model_dump_json()}}]}


class Provider:
    def __init__(self, frame=None):
        self.frame = bars() if frame is None else frame
        self.calls = []

    def fetch(self, symbol, *, index=False):
        self.calls.append((symbol, index))
        return self.frame.copy(), clock(), 10


def setup(tmp_path, calendar, model=None, provider=None):
    store = ContractStore(tmp_path / "entry.sqlite")
    p = plan(store)
    PublicationService(store).publish(plan_id=p.plan_id, runtime_id=None, published_at=clock(9, 20))
    model = model or Model()
    provider = provider or Provider()
    return store, p, EntryService(store, model=model, provider=provider, calendar=calendar), model, provider


@pytest.mark.parametrize("minute", [40, 50])
def test_causal_features_and_saved_result_ignore_appended_future(tmp_path, suspension_calendar, minute):
    store, p, service, model, provider = setup(tmp_path, suspension_calendar)
    now = clock(minute=minute)
    prior_plan = store.load_plan(p.plan_id).model_dump_json()
    prefix = bars().loc[lambda d: d.trade_time <= now.replace(tzinfo=None)]
    first = service.assess(plan_id=p.plan_id, symbol="000001", scenario="new_position", now=now, mode="historical", frame=prefix, benchmark=prefix, fetched_at=clock(16))
    assert first["state"] == "historical", first
    for future_price in (1000., .01):
        full = bars()
        future = full.trade_time > now.replace(tzinfo=None)
        full.loc[future, ["open", "high", "low", "close", "amount"]] = future_price
        value = service.assess(plan_id=p.plan_id, symbol="000001", scenario="new_position", now=now, mode="historical", frame=full, benchmark=full, fetched_at=clock(17))
        assert value["assessment"] == first["assessment"]
    assert len(model.calls) == 1
    assert model.calls[0]["evidence"]["cutoff"] == now.isoformat()
    assert store.load_plan(p.plan_id).model_dump_json() == prior_plan
    assert provider.calls == []


def test_incomplete_bar_and_publication_lag():
    now = clock(minute=42)
    assert normalize(bars(), now).iloc[-1].trade_time == pd.Timestamp(clock())
    assert normalize(bars("14:35"), clock()).iloc[-1].trade_time == pd.Timestamp(clock(minute=35))
    with pytest.raises(MinuteDataError, match="stale"):
        normalize(bars("14:30"), clock())


@pytest.mark.parametrize("change,error", [
    (lambda d: d.assign(trade_time=d.trade_time - timedelta(days=1)), "target_session"),
    (lambda d: d.iloc[::-1], "order_or_duplicate"),
    (lambda d: pd.concat([d, d.tail(1)]), "order_or_duplicate"),
    (lambda d: d.drop(d.index[-3]), "recent_minutes"),
    (lambda d: d.assign(amount=d.amount * 100), "units_or_price"),
    (lambda d: d.assign(vol=0, amount=0), "recent_minutes"),
])
def test_data_errors_are_not_stock_verdicts(tmp_path, suspension_calendar, change, error):
    store, p, service, model, _ = setup(tmp_path, suspension_calendar, provider=Provider(change(bars("14:40"))))
    result = service.assess(plan_id=p.plan_id, symbol="000001", scenario="new_position", now=clock())
    assert result["state"] == "unavailable"
    assert error in result["error"]
    assert result["assessment"] is None
    assert model.calls == []


@pytest.mark.parametrize("now", [clock(15, 1), clock(14, 57), clock(14, 40, 25), datetime(2026, 10, 1, 14, 40, tzinfo=TZ)])
def test_session_window_never_downloads_or_uses_cross_day_cache(tmp_path, suspension_calendar, now):
    store, p, service, model, provider = setup(tmp_path, suspension_calendar)
    service.assess(plan_id=p.plan_id, symbol="000001", scenario="new_position", now=clock())
    count = len(provider.calls)
    result = service.assess(plan_id=p.plan_id, symbol="000001", scenario="new_position", now=now)
    assert not result["current"]
    assert result["state"] == "unavailable"
    assert len(provider.calls) == count
    assert not service.read(p.plan_id, "000001", "new_position", now=now)["current"]


def test_reuse_failure_and_recovery_do_not_lock_weakness(tmp_path, suspension_calendar):
    store, p, service, model, provider = setup(tmp_path, suspension_calendar, model=Model("do_not_enter", "weakening"))
    first = service.assess(plan_id=p.plan_id, symbol="000001", scenario="new_position", now=clock())
    second = service.assess(plan_id=p.plan_id, symbol="000001", scenario="new_position", now=clock(minute=41))
    assert second["assessment"] == first["assessment"]
    assert len(provider.calls) == 2
    model.action, model.trend = "consider_entry", "repairing"
    result = service.assess(plan_id=p.plan_id, symbol="000001", scenario="new_position", now=clock(minute=50))
    assert result["assessment"]["judgment"]["action"] == "consider_entry"
    assert result["assessment"]["previous_assessment_id"] == first["assessment"]["assessment_id"]
    assert model.calls[-1]["previous"]["judgment"]["trend"] == "weakening"


@pytest.mark.parametrize("action,scenario", [("consider_entry", "add_position")])
def test_invalid_model_action_is_failure_not_template(tmp_path, suspension_calendar, action, scenario):
    store, p, service, model, provider = setup(tmp_path, suspension_calendar, model=Model(action))
    result = service.assess(plan_id=p.plan_id, symbol="000001", scenario=scenario, now=clock())
    assert result["state"] == "unavailable"
    assert "model_action_conflict" in result["error"]
    assert result["assessment"] is None


@pytest.mark.parametrize("name,closes", [
    ("day_up_tail_weak", [10.9,10.8,10.7,10.6,10.5,10.4,10.3]),
    ("day_down_repair", [9.3,9.4,9.5,9.6,9.7,9.8,9.9]),
    ("strength", [10.2,10.3,10.4,10.5,10.6,10.7,10.8]),
    ("pullback", [10.2,10.4,10.6,10.7,10.65,10.6,10.58]),
    ("spike_reversal", [10.4,10.6,10.9,10.7,10.5,10.3,10.1]),
    ("strength_above_zone", [11.1,11.2,11.3,11.4,11.5,11.6,11.7]),
    ("mixed", [10.4,10.5,10.4,10.5,10.4,10.5,10.4]),
])
def test_features_distinguish_recent_structure_from_day_move(tmp_path, name, closes):
    store = ContractStore(tmp_path / "entry.sqlite")
    candidate = plan(store).evaluated_candidates[0]
    data = bars("14:40", closes)
    evidence = build_evidence(data, data, candidate=candidate, now=clock(), fetched_at=clock(), request_ms=1)
    assert evidence.closes_30m == tuple(closes)
    assert evidence.return_30m == pytest.approx(closes[-1] / closes[0] - 1)
    assert evidence.return_15m == pytest.approx(closes[-1] / closes[3] - 1)
    if name == "day_up_tail_weak":
        assert evidence.return_since_open > 0 > evidence.return_30m
    if name == "day_down_repair":
        assert evidence.return_since_open < 0 < evidence.return_30m
    if name == "strength_above_zone":
        assert evidence.entry_position == "above"


@pytest.mark.parametrize("partial_amount", [False, True])
def test_optional_amount_and_benchmark_do_not_fail_stock(tmp_path, suspension_calendar, partial_amount):
    class Source(Provider):
        def fetch(self, symbol, *, index=False):
            if index: raise requests.Timeout("benchmark timeout")
            return super().fetch(symbol)
    data = bars()
    if partial_amount:
        data.loc[5, "amount"] = np.nan
    else:
        data = data.drop(columns="amount")
    store, p, service, model, _ = setup(tmp_path, suspension_calendar, provider=Source(data))
    result = service.assess(plan_id=p.plan_id, symbol="000001", scenario="new_position", now=clock())
    assert result["current"]
    evidence = result["assessment"]["evidence"]
    assert evidence["vwap"] is None and evidence["benchmark_return_30m"] is None
    assert len(evidence["limitations"]) == 2


def test_reverse_historical_order_never_passes_future_previous(tmp_path, suspension_calendar):
    store, p, service, model, _ = setup(tmp_path, suspension_calendar)
    for minute in (50, 40):
        result = service.assess(plan_id=p.plan_id, symbol="000001", scenario="new_position", now=clock(minute=minute), mode="historical", frame=bars(), benchmark=bars(), fetched_at=clock(17))
        assert result["state"] == "historical"
    assert model.calls[-1]["previous"] is None
    assert not service.read(p.plan_id, "000001", "new_position", now=clock())["current"]


def test_confirmed_suspension_prevents_collection_and_is_not_weakness(tmp_path, suspension_calendar):
    store, p, service, model, provider = setup(tmp_path, suspension_calendar)
    class Facts:
        def confirmed_suspension_at(self, **kwargs): return True
    service.market_runs = Facts()
    result = service.assess(plan_id=p.plan_id, symbol="000001", scenario="new_position", now=clock())
    assert result["error"] == "ValueError:confirmed_suspension"
    assert result["assessment"] is None
    assert provider.calls == model.calls == []


def tool(name, args):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": "call", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_real_tool_loop_history_ordinal_refresh_position_and_greeting(tmp_path, suspension_calendar):
    store, p, service, model, provider = setup(tmp_path, suspension_calendar)
    # Script the model's structured calls, not a keyword router or fixed service reply.
    # Ordinals are checked against the actual bound plan context each turn.
    class Agent:
        def __init__(self):
            self.next = []
            self.inputs = []
        def available(self): return True, "ok"
        def run_chat_with_tools(self, messages, **kwargs):
            self.inputs.append(list(messages))
            if messages[-1]["role"] == "tool":
                value = json.loads(messages[-1]["content"])
                assessment = value["assessment"]
                action = assessment["judgment"]["action"] if value["current"] else "unconfirmed"
                return tool("respond", {"kind": "entry", "text": "", "references": [{"symbol": "000001", "scenario": self.scenario, "action": action, "assessment_id": assessment["assessment_id"] if value["current"] else None}]})
            return self.next.pop(0)
    agent = Agent()
    chat = ConversationService(store, narrator=agent, now_provider=lambda: clock(), planning_calendar=suspension_calendar, entry_service=service)
    agent.next = [tool("respond", {"kind": "information", "text": "你好", "references": []})]
    chat.reply(session_id="s", client_turn_id="hello", user_message="你好")
    assert provider.calls == []
    for number, (question, function, scenario) in enumerate([
        ("第一只现在能买吗", "evaluate_entry", "new_position"),
        ("重新看一下", "evaluate_entry", "new_position"),
        ("刚才不是说走弱了吗", "read_entry", "new_position"),
        ("继续", "read_entry", "new_position"),
        ("已买一部分还适合加吗", "evaluate_entry", "add_position"),
    ]):
        agent.scenario = scenario
        if scenario == "add_position": model.action = "wait"
        agent.next = [tool(function, {"symbol": "000001", "scenario": scenario})]
        result = chat.reply(session_id="s", client_turn_id=str(number), user_message=question)
        assert result["publication_id"] == store.current_publication().publication_id
        assert "依据近期证据" in result["reply"]
    history = agent.inputs[-2]
    assert any(m["role"] == "user" and m["content"] == "第一只现在能买吗" for m in history)
    assert any(m["role"] == "assistant" and "依据近期证据" in m["content"] for m in history)
    assert json.loads(history[1]["content"])["当前事实"]["用户所见顺序"] == ["000001"]
    assert model.calls[-1]["scenario"] == "add_position"
    assert len(provider.calls) == 2  # Same stock/evidence reused even across scenarios.


def test_failed_tool_cannot_be_replaced_by_information_buy_text(tmp_path, suspension_calendar):
    store, p, service, _, _ = setup(tmp_path, suspension_calendar)
    class Agent:
        def available(self): return True, "ok"
        def run_chat_with_tools(self, messages, **kwargs):
            if messages[-1]["role"] == "tool":
                return tool("respond", {"kind": "information", "text": "现在可以买", "references": []})
            return tool("evaluate_entry", {"symbol": "000001", "scenario": "new_position"})
    chat = ConversationService(store, narrator=Agent(), now_provider=lambda: clock(15, 1), planning_calendar=suspension_calendar, entry_service=service)
    with pytest.raises(ValueError, match="narration_information_invalid"):
        chat.reply(session_id="bad", client_turn_id="x", user_message="现在能买吗")
    assert store.existing_reply(session_id="bad", client_turn_id="x") is None


def test_entry_cannot_append_a_second_unbound_recommendation(tmp_path, suspension_calendar):
    store, p, service, _, _ = setup(tmp_path, suspension_calendar)
    class Agent:
        def available(self): return True, "ok"
        def run_chat_with_tools(self, messages, **kwargs):
            if messages[-1]["role"] == "tool":
                return tool("respond", {"kind": "entry", "text": "现在可以买", "references": [{"symbol": "000001", "scenario": "new_position", "action": "unconfirmed", "assessment_id": None}]})
            return tool("evaluate_entry", {"symbol": "000001", "scenario": "new_position"})
    chat = ConversationService(store, narrator=Agent(), now_provider=lambda: clock(15, 1), planning_calendar=suspension_calendar, entry_service=service)
    with pytest.raises(ValueError, match="narration_entry_free_text_forbidden"):
        chat.reply(session_id="unbound", client_turn_id="x", user_message="现在能买吗")
    assert store.existing_reply(session_id="unbound", client_turn_id="x") is None


def test_new_verified_halt_invalidates_cached_entry_without_refetch(tmp_path, suspension_calendar):
    store, p, service, model, provider = setup(tmp_path, suspension_calendar)
    class Facts:
        halted = False
        def confirmed_suspension_at(self, **kwargs): return self.halted
    facts = Facts()
    service.market_runs = facts
    result = service.assess(plan_id=p.plan_id, symbol="000001", scenario="new_position", now=clock())
    assert result["current"]
    calls = len(provider.calls)
    facts.halted = True
    for value in (service.read(p.plan_id, "000001", "new_position", now=clock(minute=41)), service.assess(plan_id=p.plan_id, symbol="000001", scenario="new_position", now=clock(minute=41))):
        assert not value["current"] and value["error"] == "ValueError:confirmed_suspension"
    assert len(provider.calls) == calls and len(model.calls) == 1


def test_first_turn_binds_visible_publication_not_latest_pointer(tmp_path, suspension_calendar):
    from .tool_helpers import respond
    from .test_contract_lifecycle import resolve_plan_target, TradingCalendarRef, PlanService
    store, p, _, _, _ = setup(tmp_path, suspension_calendar)
    visible = store.current_publication()
    target = resolve_plan_target(now=clock(9), completed_daily_date=p.daily_evidence_date, calendar=TradingCalendarRef(calendar_id="cn", revision="1", source="fixture"), is_open=True, next_open_session=clock(day=24).date(), required_daily_evidence_date=p.daily_evidence_date)
    newer = PlanService(store).get_or_create(target=target, universe=p.candidate_universe, policy=p.decision_policy, producer=p.producer.model_copy(update={"revision": "2"}), evaluated_candidates=tuple(c.model_copy(update={"symbol": "000002"}) for c in p.evaluated_candidates), serenity=p.serenity, generated_at=clock()).plan
    current = PublicationService(store).publish(plan_id=newer.plan_id, runtime_id=None, published_at=clock())
    class Agent:
        def available(self): return True, "ok"
        def run_chat_with_tools(self, messages, **kwargs): return respond("绑定用户所见计划")
    chat = ConversationService(store, narrator=Agent(), now_provider=lambda: clock(), planning_calendar=suspension_calendar)
    first = chat.reply(session_id="visible", client_turn_id="one", user_message="第一只", publication_id=visible.publication_id)
    second = chat.reply(session_id="visible", client_turn_id="two", user_message="第二只", publication_id=current.publication_id)
    assert first["publication_id"] == second["publication_id"] == visible.publication_id


def test_worker_single_stock_failure_does_not_block_other_selected(tmp_path, suspension_calendar):
    from .test_lunch_rebalance import _base_plan
    from gp_assistant.application.market_orchestrator import MarketDayOrchestrator
    store = ContractStore(tmp_path / "worker.sqlite")
    p, publication = _base_plan(store)
    symbols = [c.symbol for c in p.evaluated_candidates if c.disposition.value == "selected"]
    assert len(symbols) > 1
    class Source(Provider):
        def fetch(self, symbol, *, index=False):
            if symbol == symbols[0]: raise requests.Timeout("only this symbol failed")
            data, fetched, latency = super().fetch(symbol, index=index)
            data.trade_time += timedelta(days=1)
            return data, fetched + timedelta(days=1), latency
    service = EntryService(store, provider=Source(), model=Model("wait", "mixed"), calendar=suspension_calendar)
    worker = MarketDayOrchestrator(store, entry_service=service, spawn_fetch=False)
    worker._run_entry_if_due(now=clock(day=24))
    assert service.read(p.plan_id, symbols[0], "new_position", now=clock(day=24))["state"] == "unavailable"
    for symbol in symbols[1:]:
        assert service.read(p.plan_id, symbol, "new_position", now=clock(day=24))["current"]
    assert store.current_publication() == publication
    assert store.load_plan(p.plan_id) == p


def test_worker_elapsed_time_cannot_confirm_after_tail_window(tmp_path, suspension_calendar, monkeypatch):
    from gp_assistant.application.market_orchestrator import MarketDayOrchestrator
    from gp_assistant.application.market_runs import MarketRunStore
    store, _, service, model, provider = setup(tmp_path, suspension_calendar)
    worker = MarketDayOrchestrator(store, ledger=MarketRunStore(tmp_path / "runs.sqlite"), entry_service=service, spawn_fetch=False)
    ticks = iter((0., 125.))
    monkeypatch.setattr("gp_assistant.application.market_orchestrator.monotonic", lambda: next(ticks))
    monkeypatch.setattr("gp_assistant.application.market_orchestrator.load_cn_a_calendar", lambda: suspension_calendar)
    monkeypatch.setattr("gp_assistant.application.market_orchestrator.recover_history_database", lambda: None)
    monkeypatch.setattr(worker, "_ensure_recovery_queue", lambda **kwargs: None)
    monkeypatch.setattr(worker, "_select_due_run", lambda **kwargs: None)
    observed = []
    original = worker._run_entry_if_due
    def entry_at(*, now):
        observed.append(now)
        original(now=now)
    monkeypatch.setattr(worker, "_run_entry_if_due", entry_at)
    worker.tick(now=clock(minute=55))
    assert observed == [clock(minute=57) + timedelta(seconds=5)]
    assert not model.calls and not provider.calls


def test_forward_tables_preserve_existing_plan_and_conversation(tmp_path, suspension_calendar):
    store, p, service, _, _ = setup(tmp_path, suspension_calendar)
    publication = store.current_publication()
    store.prepare_conversation(session_id="preserved", publication_id=publication.publication_id, now=clock())
    conn = store._connect(writable=True)
    conn.execute("DROP TABLE entry_attempts")
    conn.execute("DROP TABLE entry_assessments")
    conn.close()
    store.initialize()
    assert store.load_plan(p.plan_id) == p
    assert store.current_publication() == publication
    assert store.read_conversation_session("preserved")[0].active_publication_id == publication.publication_id
    assert store.entry_history(p.plan_id, "000001", "new_position") == []


def test_model_deadline_cannot_turn_postclose_completion_into_entry(tmp_path, suspension_calendar, monkeypatch):
    store, p, service, _, _ = setup(tmp_path, suspension_calendar)
    moments = iter([0., 121.])
    monkeypatch.setattr("gp_assistant.application.entry_service.monotonic", lambda: next(moments))
    result = service.assess(plan_id=p.plan_id, symbol="000001", scenario="new_position", now=clock(minute=56))
    assert not result["current"]
    assert "expired_during_evaluation" in result["error"]
    assert result["assessment"] is None
