from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ProxyConfig:
    upstream_base_url: str
    upstream_api_key: str
    require_auth: bool
    client_tokens: list[str]

    @classmethod
    def load(cls) -> "ProxyConfig":
        base = os.getenv('UPSTREAM_BASE_URL', 'https://api.openai.com/v1')
        key = os.getenv('UPSTREAM_API_KEY', '')
        require = os.getenv('PROXY_REQUIRE_AUTH', 'false').lower() == 'true'
        tokens = [t.strip() for t in os.getenv('PROXY_CLIENT_TOKENS', '').split(',') if t.strip()]
        return cls(base, key, require, tokens)

