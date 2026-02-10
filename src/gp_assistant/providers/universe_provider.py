from __future__ import annotations

from typing import List

import json

from ..core.paths import store_dir


class UniverseProvider:
    """Lightweight universe provider.

    Reads from store/universe/universe_symbols.(txt|json):
    - TXT: one symbol per line, comments allowed with '#'
    - JSON: ["600519", "000333", ...]
    Returns a de-duplicated list of non-empty strings.
    """

    def __init__(self, filename: str | None = None) -> None:
        self.filename = filename  # optional override

    def _txt_path(self):  # noqa: ANN001
        root = store_dir() / "universe"
        return root / (self.filename or "universe_symbols.txt")

    def _json_path(self):  # noqa: ANN001
        root = store_dir() / "universe"
        return root / (self.filename or "universe_symbols.json")

    def get_symbols(self) -> List[str]:
        """Read universe symbols from json/txt with strict cleaning.

        Cleaning rules:
        - Strip whitespace
        - Remove UTF-8 BOM (\ufeff) from each item/line start
        - Skip blank lines
        - Support comments: lines starting with '#', and inline comments after '#'
        - Accept only 6-digit codes by default
        - De-duplicate while preserving order
        Meta includes raw/clean counts, removal reasons, and sample invalids.
        """
        p_json = self._json_path()
        p_txt = self._txt_path()
        meta = {
            "source": "universe:file",
            "json": str(p_json),
            "txt": str(p_txt),
            "exists": False,
            "format": None,
            "raw_count": 0,
            "cleaned_count": 0,
            "removed_counts": {
                "bom_removed": 0,
                "comment_lines_removed": 0,
                "inline_comments_stripped": 0,
                "blank_removed": 0,
                "invalid_removed": 0,
                "dedup_removed": 0,
            },
            "sample_invalid": [],
        }

        def _normalize_item(item: str) -> tuple[str | None, dict]:
            rc = {k: 0 for k in meta["removed_counts"].keys()}
            s = str(item)
            s = s.strip()
            if s.startswith("\ufeff"):
                rc["bom_removed"] += 1
                s = s.lstrip("\ufeff")
            if not s:
                rc["blank_removed"] += 1
                return None, rc
            if s.startswith("#"):
                rc["comment_lines_removed"] += 1
                return None, rc
            if "#" in s:
                rc["inline_comments_stripped"] += 1
                s = s.split("#", 1)[0].strip()
            if not s:
                rc["blank_removed"] += 1
                return None, rc
            if not (len(s) == 6 and s.isdigit()):
                rc["invalid_removed"] += 1
                return None, rc
            return s, rc

        try:
            items: list[str] = []
            if p_json.exists():
                arr = json.loads(p_json.read_text(encoding="utf-8"))
                if isinstance(arr, list):
                    items = [str(x) for x in arr]
                meta.update({"exists": True, "format": "json"})
            elif p_txt.exists():
                items = p_txt.read_text(encoding="utf-8").splitlines()
                meta.update({"exists": True, "format": "txt"})
            meta["raw_count"] = len(items)
            cleaned: list[str] = []
            seen: set[str] = set()
            for it in items:
                norm, rc = _normalize_item(it)
                for k, v in rc.items():
                    meta["removed_counts"][k] += int(v)
                if norm is None:
                    if len(meta["sample_invalid"]) < 5:
                        meta["sample_invalid"].append(it)
                    continue
                if norm in seen:
                    meta["removed_counts"]["dedup_removed"] += 1
                    continue
                seen.add(norm)
                cleaned.append(norm)
            meta["cleaned_count"] = len(cleaned)
            out = cleaned
        except Exception:
            out = []
            meta["error"] = "read_failed"
        self._last_meta = meta
        return out

    def last_meta(self) -> dict:
        return getattr(self, "_last_meta", {"source": "universe:file", "exists": False})
