from __future__ import annotations

from hashlib import sha256


def content_id(prefix: str, canonical_json: str) -> str:
    return f"{prefix}_{sha256(canonical_json.encode('utf-8')).hexdigest()[:24]}"
