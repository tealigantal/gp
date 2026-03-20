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
    # Disable client-side timeout to support long generations
    async with httpx.AsyncClient(timeout=None) as client:
        r = await client.post(url, headers=headers, content=payload)
    return r.json()


# Support beta path to align with strict tool schema clients
@app.post('/beta/chat/completions')
async def chat_completions_beta(req: Request, cfg: ProxyConfig = Depends(get_cfg), _auth=Depends(check_auth)):
    payload = await req.body()
    headers = {
        'Authorization': f'Bearer {cfg.upstream_api_key}',
        'Content-Type': 'application/json; charset=utf-8',
        'Accept': 'application/json',
    }
    url = cfg.upstream_base_url.rstrip('/') + '/chat/completions'
    async with httpx.AsyncClient(timeout=None) as client:
        r = await client.post(url, headers=headers, content=payload)
    return r.json()


@app.get('/health')
async def health() -> dict:
    return {"status": "ok"}
