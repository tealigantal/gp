from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

from gp_assistant.providers import akshare_provider
from gp_assistant.providers.akshare_provider import AkShareProvider, _write_snapshot_cache


def _configure_provider(tmp_path, monkeypatch, api, *, disk_ttl=300):  # noqa: ANN001
    monkeypatch.setattr(akshare_provider, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        akshare_provider,
        "load_config",
        lambda: SimpleNamespace(
            cache_refresh_ttl_sec=disk_ttl,
            ak_spot_refresh_ttl_sec=30,
            ak_spot_priority=["sina"],
        ),
    )
    provider = AkShareProvider()
    monkeypatch.setattr(provider, "_import", lambda: api)
    monkeypatch.setattr(provider, "_call_with_hard_timeout", lambda fn, **_kwargs: fn())
    monkeypatch.setattr(provider, "_with_requests_timeout", lambda fn: fn())
    monkeypatch.setattr(provider, "_call_with_retry", lambda fn, retries=3: fn())
    return provider


def _live_frame():
    return pd.DataFrame(
        {
            "代码": ["600519"],
            "名称": ["贵州茅台"],
            "最新价": [1800.0],
            "涨跌幅": [1.0],
            "涨跌额": [18.0],
            "昨收": [1782.0],
            "今开": [1790.0],
            "最高": [1810.0],
            "最低": [1788.0],
            "成交量": [30000],
            "成交额": [3e9],
        }
    )


def test_fresh_disk_snapshot_without_verified_metadata_is_refetched(tmp_path, monkeypatch):
    pd.DataFrame({"code": ["000001"]}).to_pickle(tmp_path / "ak_spot_snapshot.pkl")
    calls = []

    class FakeAkShare:
        def stock_zh_a_spot(self):
            calls.append("sina")
            return _live_frame()

    provider = _configure_provider(tmp_path, monkeypatch, FakeAkShare())

    result = provider.get_spot_snapshot()

    assert calls == ["sina"]
    assert list(result["code"]) == ["600519"]
    assert (tmp_path / "ak_spot_snapshot.meta.json").exists()


def test_fresh_disk_snapshot_with_verified_metadata_avoids_live_route(tmp_path, monkeypatch):
    cached = pd.DataFrame({"code": ["000001"], "symbol": ["sz000001"], "name": ["平安银行"]})
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    _write_snapshot_cache(
        cached,
        tmp_path / "ak_spot_snapshot.pkl",
        tmp_path / "ak_spot_snapshot.meta.json",
        source="akshare:sina",
        captured_at=now.isoformat(),
        session_date=now.date().isoformat(),
    )

    class UnexpectedAkShare:
        def stock_zh_a_spot(self):
            raise AssertionError("verified file cache should avoid the live route")

    provider = _configure_provider(tmp_path, monkeypatch, UnexpectedAkShare())

    result = provider.get_spot_snapshot()

    assert list(result["code"]) == ["000001"]
    assert provider.last_snapshot_meta()["snapshot_session_date"] == now.date().isoformat()


def test_digest_mismatch_forces_live_refetch(tmp_path, monkeypatch):
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    _write_snapshot_cache(
        pd.DataFrame({"code": ["000001"]}),
        tmp_path / "ak_spot_snapshot.pkl",
        tmp_path / "ak_spot_snapshot.meta.json",
        source="akshare:sina",
        captured_at=now.isoformat(),
        session_date=now.date().isoformat(),
    )
    pd.DataFrame({"code": ["000002"]}).to_pickle(tmp_path / "ak_spot_snapshot.pkl")
    calls = []

    class FakeAkShare:
        def stock_zh_a_spot(self):
            calls.append("sina")
            return _live_frame()

    provider = _configure_provider(tmp_path, monkeypatch, FakeAkShare())

    result = provider.get_spot_snapshot()

    assert calls == ["sina"]
    assert list(result["code"]) == ["600519"]


def test_disk_cache_read_does_not_extend_original_capture_ttl(tmp_path, monkeypatch):
    cached = pd.DataFrame({"code": ["000001"], "symbol": ["sz000001"], "name": ["平安银行"]})
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    disk_path = tmp_path / "ak_spot_snapshot.pkl"
    meta_path = tmp_path / "ak_spot_snapshot.meta.json"
    _write_snapshot_cache(
        cached,
        disk_path,
        meta_path,
        source="akshare:sina",
        captured_at=now.isoformat(),
        session_date=now.date().isoformat(),
    )
    calls = []

    class FakeAkShare:
        def stock_zh_a_spot(self):
            calls.append("sina")
            return _live_frame()

    provider = _configure_provider(tmp_path, monkeypatch, FakeAkShare(), disk_ttl=300)

    first = provider.get_spot_snapshot()
    _write_snapshot_cache(
        cached,
        disk_path,
        meta_path,
        source="akshare:sina",
        captured_at=(now - timedelta(minutes=5, seconds=1)).isoformat(),
        session_date=now.date().isoformat(),
    )
    second = provider.get_spot_snapshot()

    assert list(first["code"]) == ["000001"]
    assert list(second["code"]) == ["600519"]
    assert calls == ["sina"]


def test_expired_fallback_is_never_promoted_to_fresh_memory_cache(tmp_path, monkeypatch):
    cached = pd.DataFrame({"code": ["000001"], "symbol": ["sz000001"], "name": ["平安银行"]})
    captured = datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(minutes=5)
    _write_snapshot_cache(
        cached,
        tmp_path / "ak_spot_snapshot.pkl",
        tmp_path / "ak_spot_snapshot.meta.json",
        source="akshare:sina",
        captured_at=captured.isoformat(),
        session_date=captured.date().isoformat(),
    )
    calls = []

    class FailingAkShare:
        def stock_zh_a_spot(self):
            calls.append("sina")
            raise RuntimeError("source unavailable")

    provider = _configure_provider(tmp_path, monkeypatch, FailingAkShare(), disk_ttl=1)

    first = provider.get_spot_snapshot()
    first_meta = provider.last_snapshot_meta()
    second = provider.get_spot_snapshot()
    second_meta = provider.last_snapshot_meta()

    assert list(first["code"]) == ["000001"]
    assert list(second["code"]) == ["000001"]
    assert calls == ["sina", "sina"]
    assert first_meta["fallback"] is True and first_meta["stale"] is True
    assert second_meta["fallback"] is True and second_meta["stale"] is True
