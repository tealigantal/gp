from __future__ import annotations

import sys
import os
from typing import Any, Dict, List

import pandas as pd

from ..core.config import load_config
from ..providers.factory import get_provider
from .datahub import MarketDataHub
from .theme_pool import build_themes
from ..strategy import library as strat_lib
from ..strategy.indicators import compute_indicators
from ..strategy.chip_model import compute_chip


def _recent_window_bands(df: pd.DataFrame, win: int) -> Dict[str, float]:
    x = df.tail(max(30, win))
    q30 = float(x['close'].quantile(0.30)) if 'close' in x.columns else 0.0
    q50 = float(x['close'].quantile(0.50)) if 'close' in x.columns else 0.0
    q80 = float(x['close'].quantile(0.80)) if 'close' in x.columns else 0.0
    return {'S1': q30, 'S2': q50, 'R1': q80, 'R2': (q80 * 1.02 if q80 else 0.0)}


def main() -> int:
    cfg = load_config()
    mode = (os.getenv('GP_SELF_CHECK_MODE') or '').strip().lower()
    if mode == 'contract':
        try:
            from .self_check_contract import main as contract_main

            rc = int(contract_main())
            if rc == 0:
                print('[self-check] contract: ok')
            return rc
        except Exception as e:
            print(f"[self-check] contract mode error: {e}")
            return 2

    hub = MarketDataHub()
    provider = get_provider()
    # Snapshot and themes (best effort)
    try:
        snap = provider.get_spot_snapshot()
    except Exception as e:
        snap = None
        print(f"[self-check] snapshot error: {e}")
    themes = build_themes(hub, snapshot=snap)
    cols = list(map(str, snap.columns)) if isinstance(snap, pd.DataFrame) else []
    print('[self-check] themes source:', (themes[0].get('source') if themes else 'none'))
    print('[self-check] snapshot cols:', ','.join(cols[:12]))
    print('[self-check] top themes:', [(t.get('name'), t.get('strength')) for t in themes[:2]])

    # Symbols to inspect
    syms = ['sz002969', 'sz002455', 'sh601869']
    # choose a representative strategy
    strat = (strat_lib.REGISTRY or {}).get('S8') or next(iter((strat_lib.REGISTRY or {}).values()))

    bad = 0
    for s in syms:
        try:
            df, _ = hub.daily_ohlcv(s, None, min_len=250)
            feat = compute_indicators(df)
            last_close = float(feat['close'].iloc[-1])
            # detect setups
            try:
                detect = getattr(strat, 'detect_setups', None)
                setups = detect(feat) if callable(detect) else []
                setup = setups[-1] if setups else None
                setup_idx = int(getattr(setup, 'idx', len(feat)-1)) if setup is not None else len(feat)-1
            except Exception:
                setup = None
                setup_idx = len(feat)-1
            setup_age = (len(feat)-1) - setup_idx
            # bands
            diag: Dict[str, Any] = {}
            bands: Dict[str, float] = {}
            try:
                kb = getattr(strat, 'key_bands', None)
                if callable(kb) and setup is not None:
                    bands = kb(feat, setup) or {}
            except Exception:
                bands = {}
            if (not bands) or setup_age > int(getattr(cfg, 'keyband_stale_threshold', 10)):
                bands = _recent_window_bands(feat, int(getattr(cfg, 'keyband_recent_window', 60)))
                diag['fallback_reason'] = 'stale_setup_or_no_bands'
            # sanity check
            if bands:
                r1 = float(bands.get('R1', 0.0)); s1 = float(bands.get('S1', 0.0))
                hi_ratio = (r1 / last_close) if last_close else 1.0
                lo_ratio = (last_close / s1) if s1 else 1.0
                if hi_ratio > float(getattr(cfg, 'bands_sanity_ratio', 3.0)) or lo_ratio > float(getattr(cfg, 'bands_sanity_ratio', 3.0)):
                    diag['sanity_warning'] = 'key_bands_out_of_scale_fallback'
                    bands = _recent_window_bands(feat, int(getattr(cfg, 'keyband_recent_window', 60)))
            # chip
            chip, _m = compute_chip(feat)
            warn = getattr(chip, 'sanity_warning', None)
            print(f"[self-check] {s} last_close={last_close:.2f} setup_idx={setup_idx} setup_age={setup_age} bands={bands} chip=({chip.band_90_low:.2f},{chip.avg_cost:.2f},{chip.band_90_high:.2f}) warn={warn or diag.get('sanity_warning')} reason={diag.get('fallback_reason')}")
        except Exception as e:
            print(f"[self-check] {s}: error {e}")
            bad += 1
    # Contract check: recommendation card event payload.meta
    try:
        from ..chat.orchestrator import handle_message as _hm
        from ..chat import event_store as _es
        sid = None
        _ = _hm(sid, "推荐一下")
        # resolve latest conversation id
        convs = _es.list_conversations()
        last_cid = convs[-1]["id"] if convs else ""
        # fetch latest recommendation card
        evs = _es.list_events_after(last_cid, 0, limit=200)
        ok_meta = False
        for e in (evs or [])[::-1]:
            d = e.get('data') or {}
            if d.get('kind') == 'card' and (d.get('payload') or {}).get('type') == 'recommendation':
                meta = (d.get('payload') or {}).get('meta')
                if isinstance(meta, dict) and 'as_of' in meta and isinstance(meta.get('themes'), list):
                    ok_meta = True
                    break
        if not ok_meta:
            print('[self-check] event payload.meta missing or invalid')
            return 2
    except Exception as e:
        print(f"[self-check] event contract check skipped: {e}")
    # Non-contract mode：联网失败/数据异常不应导致退出码=1
    return 0

if __name__ == '__main__':
    sys.exit(main())
