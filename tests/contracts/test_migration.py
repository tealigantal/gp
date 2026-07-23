import json
import sqlite3

import pytest

from gp_assistant.migrate_contracts import migrate
from gp_assistant.store import ContractStore, UnsupportedDatabaseSchema
from .test_contract_lifecycle import plan


def test_old_schema_is_rejected_and_migration_maps_exact_embedded_contract(tmp_path):
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    table = "recommendation_" + "snapshots"
    conn.execute(f"CREATE TABLE {table}(payload_json TEXT NOT NULL)")
    with pytest.raises(UnsupportedDatabaseSchema):
        ContractStore(path).initialize()
    staging = ContractStore(tmp_path / "staging.sqlite")
    recommendation_plan = plan(staging)
    from gp_assistant.application.publication_service import PublicationService
    publication = PublicationService(staging).publish(plan_id=recommendation_plan.plan_id, runtime_id=None, published_at=recommendation_plan.generated_at)
    conn.execute(f"INSERT INTO {table}(payload_json) VALUES(?)", (json.dumps({"recommendation_plan": recommendation_plan.model_dump(mode="json"), "recommendation_publication": publication.model_dump(mode="json")}),))
    conn.commit()
    conn.close()
    report = migrate(path, writers_stopped=True)
    assert report["migrated_publications"] == 1
    store = ContractStore(path)
    assert store.current_publication().publication_id == publication.publication_id
    check = sqlite3.connect(path)
    names = {row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "recommendation_" + "snapshots" not in names
    assert check.execute("PRAGMA foreign_key_check").fetchall() == []
    assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    check.close()
