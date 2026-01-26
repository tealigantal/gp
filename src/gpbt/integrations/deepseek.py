from __future__ import annotations

import json
import os
from typing import Iterable, List, Optional

import requests


def _load_api_key() -> Optional[str]:
    key = os.getenv("DEEPSEEK_API_KEY")
    if key:
        return key
    try:
        # Optional local file (gitignored)
        from local_secrets import DEEPSEEK_API_KEY  # type: ignore
        return DEEPSEEK_API_KEY  # noqa: F401
    except Exception:
        return None


class DeepSeekClient:
    def __init__(self, base_url: str = "https://api.deepseek.com", model: str = "deepseek-chat"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        api_key = _load_api_key()
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未设置。请设置环境变量或在 local_secrets.py 中定义 DEEPSEEK_API_KEY")
        self.api_key = api_key

    def chat(self, messages: List[dict], temperature: float = 0.2, max_tokens: int = 512) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json; charset=utf-8",
            "Accept-Charset": "utf-8",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        resp = requests.post(url, headers=headers, data=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


def tag_announcement_titles(client: DeepSeekClient, titles: Iterable[str]) -> List[dict]:
    """对公告标题做轻量分类与打分（演示用途）。
    返回 [{title, label, score}]，label∈{positive, neutral, negative}，score∈[-1,1]
    """
    titles_list = [t for t in titles if t]
    if not titles_list:
        return []
    system = {
        "role": "system",
        "content": "你是量化助手。请将给定的公告标题逐条判定情绪：positive/neutral/negative，并给一个-1到1之间的分数。仅输出JSON数组。键为title,label,score。"
    }
    user = {
        "role": "user",
        "content": "\n".join(titles_list)
    }
    text = client.chat([system, user], temperature=0.0, max_tokens=800)
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    # 兜底：全部标为 neutral 0
    return [{"title": t, "label": "neutral", "score": 0.0} for t in titles_list]
