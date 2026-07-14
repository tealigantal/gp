from types import SimpleNamespace

import pytest

from gp_assistant.serenity import worker


def test_resident_loop_waits_for_a_previous_lease_instead_of_crashing(monkeypatch):
    monkeypatch.setattr(worker, "load_config", lambda: SimpleNamespace(serenity=SimpleNamespace(mode="native", lease_sec=30)))
    monkeypatch.setattr(worker, "initialize_store", lambda: None)
    acquired = iter((False, True))
    monkeypatch.setattr(worker, "acquire_worker_lease", lambda _owner: next(acquired))
    sleeps: list[float] = []
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(worker, "release_worker_lease", lambda _owner: None)

    class Heartbeater:
        def __init__(self, *_args):
            pass

        def start(self):
            pass

        def assert_owned(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(worker, "_LeaseHeartbeater", Heartbeater)
    monkeypatch.setattr(worker, "_run_serenity_once_owned", lambda **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        worker.run_serenity_loop()

    assert sleeps == [10.0]


def test_resident_loop_bootstraps_then_immediately_runs_live(monkeypatch):
    monkeypatch.setattr(worker, "load_config", lambda: SimpleNamespace(serenity=SimpleNamespace(mode="native", lease_sec=30)))
    monkeypatch.setattr(worker, "initialize_store", lambda: None)
    monkeypatch.setattr(worker, "acquire_worker_lease", lambda _owner: True)
    monkeypatch.setattr(worker, "release_worker_lease", lambda _owner: None)
    bootstrap_state = iter((None, {"bootstrap_id": "ready"}))
    monkeypatch.setattr(worker, "latest_complete_bootstrap", lambda: next(bootstrap_state))

    class Heartbeater:
        def __init__(self, *_args):
            pass

        def start(self):
            pass

        def assert_owned(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(worker, "_LeaseHeartbeater", Heartbeater)
    calls = []

    def run_once(**kwargs):
        calls.append(bool(kwargs.get("bootstrap")))
        if len(calls) == 1:
            return {"bootstrap_complete": True, "schedule": {"delay_sec": 999}}
        raise KeyboardInterrupt()

    monkeypatch.setattr(worker, "_run_serenity_once_owned", run_once)
    monkeypatch.setattr(worker.time, "sleep", lambda _seconds: pytest.fail("bootstrap success must not sleep before live poll"))

    with pytest.raises(KeyboardInterrupt):
        worker.run_serenity_loop()

    assert calls == [True, False]


def test_resident_loop_repolls_immediately_when_target_changes(monkeypatch):
    monkeypatch.setattr(worker, "load_config", lambda: SimpleNamespace(serenity=SimpleNamespace(mode="native", lease_sec=30)))
    monkeypatch.setattr(worker, "initialize_store", lambda: None)
    monkeypatch.setattr(worker, "acquire_worker_lease", lambda _owner: True)
    monkeypatch.setattr(worker, "release_worker_lease", lambda _owner: None)
    monkeypatch.setattr(worker, "latest_complete_bootstrap", lambda: {"bootstrap_id": "ready"})
    monkeypatch.setattr(worker, "load_stable_targets", lambda: {"target_id": "target-b"})

    class Heartbeater:
        def __init__(self, *_args):
            pass

        def start(self):
            pass

        def assert_owned(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(worker, "_LeaseHeartbeater", Heartbeater)
    calls = []

    def run_once(**_kwargs):
        calls.append(True)
        if len(calls) == 1:
            return {
                "target_meta": {"target_id": "target-a"},
                "schedule": {"delay_sec": 999},
            }
        raise KeyboardInterrupt()

    monkeypatch.setattr(worker, "_run_serenity_once_owned", run_once)
    monkeypatch.setattr(
        worker.time,
        "sleep",
        lambda _seconds: pytest.fail("target switch must not enter scheduler sleep"),
    )

    with pytest.raises(KeyboardInterrupt):
        worker.run_serenity_loop()

    assert len(calls) == 2


def test_resident_loop_observes_target_published_while_scheduler_is_waiting(monkeypatch):
    monkeypatch.setattr(worker, "load_config", lambda: SimpleNamespace(serenity=SimpleNamespace(mode="native", lease_sec=90)))
    monkeypatch.setattr(worker, "initialize_store", lambda: None)
    monkeypatch.setattr(worker, "acquire_worker_lease", lambda _owner: True)
    monkeypatch.setattr(worker, "release_worker_lease", lambda _owner: None)
    monkeypatch.setattr(worker, "latest_complete_bootstrap", lambda: {"bootstrap_id": "ready"})
    target_states = iter(({}, {"target_id": "target-a"}))
    monkeypatch.setattr(worker, "load_stable_targets", lambda: next(target_states))

    class Heartbeater:
        def __init__(self, *_args):
            pass

        def start(self):
            pass

        def assert_owned(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(worker, "_LeaseHeartbeater", Heartbeater)
    calls = []

    def run_once(**_kwargs):
        calls.append(True)
        if len(calls) == 1:
            return {
                "target_meta": {"ok": False, "reason": "candidate_target_unavailable"},
                "schedule": {"delay_sec": 999},
            }
        raise KeyboardInterrupt()

    monkeypatch.setattr(worker, "_run_serenity_once_owned", run_once)
    sleeps: list[float] = []
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(KeyboardInterrupt):
        worker.run_serenity_loop()

    assert calls == [True, True]
    assert sleeps == [30.0]


def test_resident_open_breaker_waits_instead_of_spinning(monkeypatch):
    monkeypatch.setattr(
        worker,
        "load_config",
        lambda: SimpleNamespace(serenity=SimpleNamespace(mode="native", lease_sec=90)),
    )
    monkeypatch.setattr(worker, "initialize_store", lambda: None)
    monkeypatch.setattr(worker, "acquire_worker_lease", lambda _owner: True)
    monkeypatch.setattr(worker, "release_worker_lease", lambda _owner: None)
    monkeypatch.setattr(
        worker, "latest_complete_bootstrap", lambda: {"bootstrap_id": "ready"}
    )
    monkeypatch.setattr(
        worker, "load_stable_targets", lambda: {"target_id": "target-a"}
    )

    class Heartbeater:
        def __init__(self, *_args):
            pass

        def start(self):
            pass

        def assert_owned(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(worker, "_LeaseHeartbeater", Heartbeater)
    calls = 0

    def run_once(**_kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            pytest.fail("circuit-open loop retried before sleeping")
        return {
            "status": "circuit_open",
            "complete": False,
            "schedule": {"delay_sec": 1800},
        }

    class Slept(Exception):
        pass

    def sleep(seconds):
        assert seconds == 30.0
        raise Slept

    monkeypatch.setattr(worker, "_run_serenity_once_owned", run_once)
    monkeypatch.setattr(worker.time, "sleep", sleep)

    with pytest.raises(Slept):
        worker.run_serenity_loop()

    assert calls == 1
