from __future__ import annotations

"""One-time destructive replacement of a pre-contract SQLite database.

This module is the sole source location allowed to inspect the retired schema.
It is not imported by normal application startup.
"""

import json
import os
from pathlib import Path
import shutil
import sqlite3
from tempfile import NamedTemporaryFile
from time import sleep

from .contracts.decision import RecommendationPlan
from .contracts.publication import RecommendationPublication
from .contracts.runtime import RuntimeObservation
from .store import ContractStore, DATABASE_SCHEMA


class MigrationBlocked(RuntimeError):
    pass


def _legacy_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {name: int(conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]) if name in tables else 0 for name in ("recommendation_snapshots", "current_snapshot", "daybook_versions", "sessions", "turns", "claims")}


def migrate(database: str | Path, *, writers_stopped: bool | None = None) -> dict[str, object]:
    """Atomically replace the active file; only exact embedded canonical rows survive."""
    source = Path(database).resolve()
    if not source.exists():
        raise MigrationBlocked("database_not_found")
    if writers_stopped is None:
        writers_stopped = os.getenv("GP_CONTRACT_WRITERS_STOPPED") == "1"
    if not writers_stopped:
        raise MigrationBlocked("writers_must_be_stopped")
    old = sqlite3.connect(source, timeout=1, isolation_level=None)
    backup = source.with_name(f".{source.name}.contract-cutover-backup")
    replacement: Path | None = None
    report: dict[str, object] = {"source": str(source), "migrated_publications": 0, "discarded": {}, "counts": {}}
    try:
        old.execute("PRAGMA foreign_keys=ON")
        tables = {str(row[0]) for row in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "schema_metadata" in tables:
            schema_row = old.execute("SELECT value FROM schema_metadata WHERE key='schema'").fetchone()
            if schema_row and str(schema_row[0]) == DATABASE_SCHEMA:
                raise MigrationBlocked("database_already_contract_kernel_v1")
            raise MigrationBlocked("database_schema_not_legacy")
        report["counts"] = _legacy_counts(old)
        if backup.exists():
            if backup.stat().st_size < source.stat().st_size:
                backup.unlink()
            else:
                raise MigrationBlocked("temporary_backup_already_exists")
        before = source.stat()
        version_before = int(old.execute("PRAGMA data_version").fetchone()[0])
        sleep(0.05)
        after = source.stat()
        version_after = int(old.execute("PRAGMA data_version").fetchone()[0])
        if (before.st_size, before.st_mtime_ns, version_before) != (after.st_size, after.st_mtime_ns, version_after):
            raise MigrationBlocked("database_is_being_written")
        shutil.copy2(source, backup)
        old.execute("BEGIN EXCLUSIVE")
        with NamedTemporaryFile(prefix=f".{source.name}.contract-", suffix=".sqlite", dir=source.parent, delete=False) as temporary:
            replacement = Path(temporary.name)
        destination = ContractStore(replacement)
        destination.initialize()
        discarded = 0
        if "recommendation_snapshots" in tables:
            rows = old.execute("SELECT payload_json FROM recommendation_snapshots").fetchall()
            recovered: list[tuple[RecommendationPlan, RuntimeObservation | None, RecommendationPublication]] = []
            for row in rows:
                try:
                    raw = json.loads(str(row[0]))
                    plan = RecommendationPlan.model_validate(raw["recommendation_plan"])
                    runtime = RuntimeObservation.model_validate(raw["runtime_observation"]) if raw.get("runtime_observation") is not None else None
                    publication = RecommendationPublication.model_validate(raw["recommendation_publication"])
                    recovered.append((plan, runtime, publication))
                except Exception:
                    discarded += 1
            for plan, runtime, publication in sorted(recovered, key=lambda item: (item[2].published_at, item[2].publication_id)):
                try:
                    destination.commit_plan(plan)
                    if runtime is not None:
                        destination.commit_runtime(runtime)
                    current = destination.current_publication()
                    destination.commit_publication(
                        publication,
                        expected_current_publication_id=current.publication_id if current else None,
                    )
                    report["migrated_publications"] = int(report["migrated_publications"]) + 1
                except Exception:
                    discarded += 1
        report["discarded"] = {"unmappable_retired_rows": discarded}
        check = sqlite3.connect(replacement)
        try:
            foreign = check.execute("PRAGMA foreign_key_check").fetchall()
            integrity = str(check.execute("PRAGMA integrity_check").fetchone()[0])
            if foreign or integrity.lower() != "ok":
                raise MigrationBlocked("replacement_validation_failed")
        finally:
            check.close()
        old.execute("COMMIT")
        old.close()
        old = None
        os.replace(replacement, source)
        replacement = None
        ContractStore(source).initialize()
        backup.unlink()
        return report
    except BaseException:
        if old is not None:
            if old.in_transaction:
                old.execute("ROLLBACK")
            old.close()
        if replacement and replacement.exists():
            replacement.unlink()
        raise
