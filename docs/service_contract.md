# Service Output Contract

This document defines the JSON schema for recommendation outputs written to `store/recommend/{date}.json` and `store/recommend/latest.json`.

File layout:
- `store/recommend/{date}.json` — daily recommendation result (preopen/intraday/close stages)
- `store/recommend/latest.json` — the latest published result (symlink-like copy)

Schema (minimum fields):
{
  "as_of": "YYYYMMDD HH:MM:SS",
  "timezone": "Asia/Shanghai",
  "tradeable": true,
  "message": "human-readable status",
  "disclaimer": "disclaimer text",
  "stage": "preopen|intraday|close",
  "picks": [
    {
      "symbol": "000001.SZ",
      "name": "optional company name",
      "theme": "optional theme or concept",
      "champion": { "strategy": "name", "score": 0.0, "params_hash": "...", "scenario": "base" },
      "trade_plan": { "entry": 0.0, "stop": 0.0, "take": 0.0, "bands": {}, "actions": {} },
      "tags": ["info", "risk"],
      "risk": { "max_position": 0.1, "cooldown": 0 },
      "debug": {}
    }
  ],
  "debug": { "mode": "service", "degraded": false, "reasons": [] }
}

Notes:
- Fields must remain stable to avoid breaking the frontend. Additional fields can be added under `debug`.
- The `champion` sub-object freezes the strategy identity used to generate the pick.
- Intraday updates should preserve required keys and only update fields (e.g., signals, actions, metrics).

