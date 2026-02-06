from __future__ import annotations

from fastapi import FastAPI, Request, Depends
import httpx

from .config import ProxyConfig
from .auth import check_auth


app = FastAPI()


def get_cfg() -> ProxyConfig:
    return ProxyConfig.load()


@app.post('/v1/chat/completions')
async def chat_completions(req: Request, cfg: ProxyConfig = Depends(get_cfg), _auth=Depends(check_auth)):
    payload = await req.body()
    headers = {
        'Authorization': f'Bearer {cfg.upstream_api_key}',
        'Content-Type': 'application/json; charset=utf-8',
        'Accept': 'application/json',
    }
    url = cfg.upstream_base_url.rstrip('/') + '/chat/completions'
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=headers, content=payload)
    return r.json()

