from __future__ import annotations

import os
import json
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from ..core.paths import store_dir


ARTIFACT_SCHEMA_VERSION = "gp.runtime-artifact.v3"
SELECTION_POLICY = "adaptive_v2_native_serenity_single_score"


@lru_cache(maxsize=1)
def _source_digest() -> str:
    root = Path(__file__).resolve().parents[1]
    digest = sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _build_revision() -> str:
    configured = str(os.getenv("GP_BUILD_REVISION") or "").strip()
    if configured and configured not in {"local", "dev"}:
        return configured
    return f"source-{_source_digest()}"


def producer_metadata() -> dict[str, str]:
    return {
        "revision": _build_revision(),
        "source_digest": _source_digest(),
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "selection_policy": SELECTION_POLICY,
    }


def producer_is_compatible(value: Mapping[str, Any] | None) -> bool:
    producer = dict(value or {})
    return (
        str(producer.get("revision") or "") == producer_metadata()["revision"]
        and
        str(producer.get("source_digest") or "") == producer_metadata()["source_digest"]
        and
        str(producer.get("schema_version") or "") == ARTIFACT_SCHEMA_VERSION
        and str(producer.get("selection_policy") or "") == SELECTION_POLICY
    )


def assert_producer_compatible(value: Mapping[str, Any] | None, *, stage: str) -> None:
    if producer_is_compatible(value):
        return
    raise RuntimeError(
        f"incompatible_runtime_producer:{stage}:"
        f"expected_schema={ARTIFACT_SCHEMA_VERSION}:expected_policy={SELECTION_POLICY}"
    )


def _contract_path() -> Path:
    return store_dir() / "runtime" / "producer_contract.json"


def publish_producer_contract() -> dict[str, str]:
    producer = producer_metadata()
    path = _contract_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(producer, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return producer


def assert_deployed_producer() -> dict[str, str]:
    path = _contract_path()
    if not path.exists():
        raise RuntimeError("deployed_producer_contract_missing")
    try:
        deployed = json.loads(path.read_text(encoding="utf-8"))
    except Exception as ex:
        raise RuntimeError("deployed_producer_contract_invalid") from ex
    assert_producer_compatible(deployed, stage="deployed_contract")
    if dict(deployed) != producer_metadata():
        raise RuntimeError("deployed_producer_revision_mismatch")
    return dict(deployed)
