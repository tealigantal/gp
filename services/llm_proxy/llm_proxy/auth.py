from __future__ import annotations

from fastapi import Header, HTTPException
from .config import ProxyConfig


def check_auth(cfg: ProxyConfig, authorization: str | None = Header(default=None)) -> None:
    if not cfg.require_auth:
        return
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='Missing token')
    token = authorization.split(' ', 1)[1].strip()
    if token not in cfg.client_tokens:
        raise HTTPException(status_code=401, detail='Invalid token')

