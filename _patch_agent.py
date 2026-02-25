import re, pathlib
src_head = pathlib.Path('tmp_agent_head.py').read_text(encoding='utf-8')
pat = re.compile(r"def _trade_plan_from_strategy\(mod: Any, df_feat: pd\.DataFrame, pick: Dict\[str, Any\], q_grade: Optional\[str\]\) -> Dict\[str, Any\]:.*?\n\s*# Evaluate strategies for pool and choose champion", re.S)
rep = '''def _trade_plan_from_strategy(mod: Any, df_feat: pd.DataFrame, pick: Dict[str, Any], q_grade: Optional[str]) -> Dict[str, Any]:
    bands: Dict[str, float] = {}
    actions: Dict[str, str] = {}
    invalid: List[str] = []
    diag: Dict[str, Any] = {}
    # latest setup if available
    try:
        detect = getattr(mod, 'detect_setups', None)
        setups = detect(df_feat) if callable(detect) else []
        setup = setups[-1] if setups else None
    except Exception:
        setup = None
    # helper: recent-window bands anchored to latest bar
    def _recent_window_bands(df: pd.DataFrame) -> Dict[str, float]:
        win = max(30, int(getattr(cfg, 'keyband_recent_window', 60)))
        x = df.tail(win)
        q30 = float(x['close'].quantile(0.30)) if 'close' in x.columns else 0.0
        q50 = float(x['close'].quantile(0.50)) if 'close' in x.columns else 0.0
        q80 = float(x['close'].quantile(0.80)) if 'close' in x.columns else 0.0
        return {'S1': q30, 'S2': q50, 'R1': q80, 'R2': (q80 * 1.02 if q80 else 0.0)}
    # bands: prefer strategy, but guard against stale setups
    try:
        kb = getattr(mod, 'key_bands', None)
        if callable(kb) and setup is not None:
            bands = kb(df_feat, setup) or {}
    except Exception:
        bands = {}
    # stale detection and fallback
    try:
        last_idx = int(df_feat.index[-1]) if hasattr(df_feat.index, 'dtype') else int(len(df_feat) - 1)
    except Exception:
        last_idx = int(len(df_feat) - 1)
    setup_idx = int(getattr(setup, 'idx', last_idx)) if setup is not None else last_idx
    setup_age = max(0, last_idx - setup_idx)
    diag.update({'setup_idx': setup_idx, 'last_idx': last_idx, 'setup_age': setup_age})
    stale = bool(setup is None) or (setup_age > int(getattr(cfg, 'keyband_stale_threshold', 10)))
    diag['stale'] = stale
    if (not bands) or stale:
        bands = _recent_window_bands(df_feat)
        diag['fallback_reason'] = 'stale_setup' if stale else 'no_bands_from_strategy'
    # Actions & invalidation
    try:
        ct = getattr(mod, 'confirm_text', None)
        if callable(ct):
            t = ct(setup, q_grade or 'Q?')
            if isinstance(t, dict):
                actions = {
                    'window_A': str(t.get('window_A_text', 'A窗：关键带回收，承接成立')),
                    'window_B': str(t.get('window_B_text', 'B窗：收盘确认，不追价')),
                }
    except Exception:
        actions = {}
    try:
        inv = getattr(mod, 'invalidation', None)
        if callable(inv):
            lst = inv(setup)
            invalid = [str(x) for x in (lst or [])]
    except Exception:
        invalid = []
    # Sanity check bands vs last_close; fallback if out-of-scale
    try:
        last_close = float(df_feat['close'].iloc[-1]) if 'close' in df_feat.columns else None
        if last_close and bands:
            max_ratio = float(getattr(cfg, 'bands_sanity_ratio', 3.0))
            r1 = float(bands.get('R1', 0.0)); s1 = float(bands.get('S1', 0.0))
            hi_ratio = (r1 / last_close) if last_close else 1.0
            lo_ratio = (last_close / s1) if s1 else 1.0
            if hi_ratio > max_ratio or lo_ratio > max_ratio:
                bands = _recent_window_bands(df_feat)
                diag['sanity_warning'] = 'key_bands_out_of_scale_fallback'
    except Exception:
        pass
    risk = {'stop_loss': '收盘有效跌破支撑带', 'time_stop': '2-3日不强必走', 'no_averaging_down': True}
    return {'bands': bands, 'actions': actions, 'invalidation': invalid, 'risk': risk, 'diagnostics': diag}

    # Evaluate strategies for pool and choose champion'''
src2 = pat.sub(rep, src_head)
src2 = src2.replace('"theme": themes[0]["name"] if themes else "行业轮动",', "'theme': (cand.get('industry') or cand.get('source_reason') or '行业轮动'),\n            'market_themes': themes[:2] if isinstance(themes, list) else [],\n            'market_theme': (themes[0]['name'] if themes else None),")
pathlib.Path('src/gp_assistant/recommend/agent.py').write_text(src2, encoding='utf-8')
print('ok')
