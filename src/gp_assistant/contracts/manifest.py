from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = Path(__file__).resolve().parent
REGISTRY = ROOT / "docs" / "contracts" / "registry.yaml"
MANIFEST = ROOT / "docs" / "contracts" / "schema_manifest.json"
MODEL_FILES = ("market.py", "evidence.py", "decision.py", "runtime.py", "publication.py", "conversation.py")


def _registered() -> list[dict[str, object]]:
    return list(json.loads(REGISTRY.read_text(encoding="utf-8")))


def _models() -> dict[str, str]:
    found: dict[str, str] = {}
    for filename in MODEL_FILES:
        path = CONTRACTS / filename
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any((isinstance(base, ast.Name) and base.id == "ContractModel") or (isinstance(base, ast.Attribute) and base.attr == "ContractModel") for base in node.bases):
                found[node.name] = f"gp_assistant.contracts.{path.stem}:{node.name}"
    return found


def _forbidden_contract_text() -> list[str]:
    violations: list[str] = []
    for filename in MODEL_FILES:
        path = CONTRACTS / filename
        text = path.read_text(encoding="utf-8")
        if "Any" in text or "dict[str, Any]" in text:
            violations.append(f"forbidden_untyped_contract:{path.name}")
        if "contracts" + ".objects" in text:
            violations.append(f"removed_contract_import:{path.name}")
    return violations


def build() -> dict[str, object]:
    models = _models()
    entries = _registered()
    names = [str(entry["name"]) for entry in entries]
    violations = _forbidden_contract_text()
    if len(names) != len(set(names)):
        violations.append("duplicate_registry_name")
    if set(models) != set(names):
        violations.append("registry_model_mismatch")
    for entry in entries:
        name = str(entry["name"])
        if entry.get("python_import") != models.get(name):
            violations.append(f"registry_import_mismatch:{name}")
        for required in ("schema", "domain", "owner", "kind", "producer", "consumers", "persisted", "public", "source_of_truth", "projection_of", "primary_identity", "status"):
            if required not in entry:
                violations.append(f"registry_field_missing:{name}:{required}")
    if violations:
        raise SystemExit("\n".join(sorted(set(violations))))
    schemas = {}
    for name, import_path in models.items():
        module_name, class_name = import_path.split(":")
        module = __import__(module_name, fromlist=[class_name])
        schemas[name] = getattr(module, class_name).model_json_schema()
    return {"schema": "contract_manifest.v1", "contracts": schemas}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--write", action="store_true")
    choice.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    built = build()
    rendered = json.dumps(built, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.write:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(rendered, encoding="utf-8")
        return 0
    if not MANIFEST.exists() or MANIFEST.read_text(encoding="utf-8") != rendered:
        raise SystemExit("stale_schema_manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
