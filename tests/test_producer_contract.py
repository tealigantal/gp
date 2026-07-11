import json

import pytest

from gp_assistant.runtime import producer


def test_ops_contract_matches_running_api_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path / "store"))
    expected = producer.publish_producer_contract()
    assert producer.assert_deployed_producer() == expected


def test_ops_contract_rejects_different_revision(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path / "store"))
    path = tmp_path / "store" / "runtime" / "producer_contract.json"
    path.parent.mkdir(parents=True)
    incompatible = {**producer.producer_metadata(), "revision": "source-old"}
    path.write_text(json.dumps(incompatible), encoding="utf-8")
    with pytest.raises(RuntimeError, match="incompatible_runtime_producer|revision_mismatch"):
        producer.assert_deployed_producer()
