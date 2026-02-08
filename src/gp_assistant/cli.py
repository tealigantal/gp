from __future__ import annotations

import argparse
import json
import sys

from .core.logging import setup_logging
Agent = None  # lazy import
route_text = None  # lazy import
from .providers.factory import get_provider
from .tools.universe import build_universe
from .tools.market_data import normalize_daily_ohlcv
from .tools.signals import compute_indicators
from .tools.backtest import load_strategies, run_event_backtest, save_stats
from .tools.rank import rank_candidates
from .core.validator import validate_pick_json


def _sanitize(obj):
    import math
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    return obj


def _print_result(res) -> int:
    payload = {"ok": res.ok, "message": res.message}
    if res.data is not None:
        payload["data"] = _sanitize(res.data)
    try:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except UnicodeEncodeError:
        print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if res.ok else 1


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    # Lazy import to avoid importing optional deps during module import
    global Agent, route_text
    if Agent is None:
        from .agent.agent import Agent as _Agent  # type: ignore
        Agent = _Agent
    if route_text is None:
        from .agent.router_factory import route_text as _route_text  # type: ignore
        route_text = _route_text
    agent = Agent()

    parser = argparse.ArgumentParser(prog="gp", description="gp assistant: chat + deterministic tools")
    sub = parser.add_subparsers(dest="cmd")

    p_chat = sub.add_parser("chat", help="LLM chat; use --repl for REPL mode")
    p_chat.add_argument("query", nargs="?", help="e.g. recommend topk=3 date=2026-02-09")
    p_chat.add_argument("--repl", action="store_true", help="enter interactive REPL")

    p_bt = sub.add_parser("backtest", help="Run deterministic event backtest")
    p_bt.add_argument("--strategy", required=True)
    pref_bt = p_bt.add_mutually_exclusive_group()
    pref_bt.add_argument("--prefer-local", action="store_true", help="prefer local data if available")
    pref_bt.add_argument("--prefer-online", action="store_true", help="prefer online provider")

    p_pick = sub.add_parser("pick", help="Deterministic Top10 pick")
    p_pick.add_argument("--asof", help="as-of date YYYY-MM-DD", default=None)
    pref_pk = p_pick.add_mutually_exclusive_group()
    pref_pk.add_argument("--prefer-local", action="store_true", help="prefer local data if available")
    pref_pk.add_argument("--prefer-online", action="store_true", help="prefer online provider")

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0

    if args.cmd == "chat":
        if args.repl or not args.query:
            print("Interactive mode. Type 'exit' to quit. Example: recommend topk=3 date=2026-02-09")
            while True:
                try:
                    line = input("gp> ").strip()
                except EOFError:
                    break
                if not line:
                    continue
                if line.lower() in {"exit", "quit", ":q"}:
                    break
                route = route_text(line, agent.state)
                res = agent.run(route.tool, route.args)
                _print_result(res)
            return 0
        route = route_text(args.query, agent.state)
        res = agent.run(route.tool, route.args)
        return _print_result(res)

    if args.cmd == "backtest":
        prefer = "local" if getattr(args, "prefer_local", False) else ("online" if getattr(args, "prefer_online", False) else None)
        provider = get_provider(prefer=prefer)
        loaded = load_strategies()
        strategies = {s.id: s for s in loaded}
        strat = strategies.get(args.strategy)
        if not strat:
            for s in loaded:
                if s.id.lower() == args.strategy.lower():
                    strat = s
                    break
        if not strat and args.strategy.upper() == "S1":
            from .tools.backtest import _default_strategies
            strat = _default_strategies()[0]
        if not strat:
            return _print_result(type("Res", (), {"ok": False, "message": f"invalid strategy: {args.strategy}", "data": None}))
        cfg = getattr(agent.state, "config", None)
        uni = agent.registry.get("universe").run({}, agent.state)
        symbols = uni.data.get("symbols", []) if uni.ok and uni.data else []
        out = {}
        for sym in symbols:
            try:
                df_raw = provider.get_daily(sym, start=None, end=None)
                df_norm, _ = normalize_daily_ohlcv(df_raw)
                df_feat = compute_indicators(df_norm, None)
                df_feat.attrs["symbol"] = sym
                stats = run_event_backtest(df_feat, strat, cfg)
                save_stats(stats)
                out[sym] = stats.__dict__
            except Exception as e:  # noqa: BLE001
                out[sym] = {"error": str(e)}
        return _print_result(type("Res", (), {"ok": True, "message": "backtest done", "data": out}))

    if args.cmd == "pick":
        prefer = "local" if getattr(args, "prefer_local", False) else ("online" if getattr(args, "prefer_online", False) else None)
        provider = get_provider(prefer=prefer)
        cfg = getattr(agent.state, "config", None)
        uni_res = build_universe(provider, cfg, args.asof)
        feats = {}
        stats_by = {}
        strategies = load_strategies()
        use_strat = strategies[0]
        for e in list(uni_res.kept) + list(uni_res.watch_only):
            try:
                df_raw = provider.get_daily(e.symbol, start=None, end=args.asof)
                df_norm, _ = normalize_daily_ohlcv(df_raw)
                df_feat = compute_indicators(df_norm, None)
                df_feat.attrs["symbol"] = e.symbol
                feats[e.symbol] = df_feat
                st = run_event_backtest(df_feat, use_strat, cfg)
                stats_by[e.symbol] = st
            except Exception:
                continue
        import json as _json
        from .core.paths import store_dir as _store_dir
        champ_fp = _store_dir() / "champion.json"
        champion_state = None
        if champ_fp.exists():
            try:
                champion_state = _json.loads(champ_fp.read_text(encoding="utf-8"))
            except Exception:
                champion_state = None
        picked = rank_candidates(uni_res, feats, stats_by, champion_state=champion_state, config=cfg)
        top_serialized = []
        for it in picked.top:
            top_serialized.append({
                "symbol": it.symbol,
                "name": it.name,
                "sector": it.sector,
                "indicators": it.indicators,
                "noise_level": it.noise_level,
                "strategy_attribution": it.strategy_attribution,
                "backtest": it.backtest.__dict__,
                "risk_constraints": it.risk_constraints,
                "actions": it.actions,
                "time_stop": it.time_stop,
                "events": it.events,
                "score": it.score,
            })
        payload = {
            "top": top_serialized,
            "kept_count": picked.kept_count,
            "watch_count": picked.watch_count,
            "rejected_count": picked.rejected_count,
            "champion": champion_state or {"note": "no champion trained; using default S1"},
            "disclaimer": "本项目仅用于研究与教育，不构成任何投资建议或收益承诺。",
        }
        v = validate_pick_json(payload)
        if not v.ok:
            return _print_result(type("Res", (), {"ok": False, "message": "; ".join(v.errors), "data": payload}))
        return _print_result(type("Res", (), {"ok": True, "message": "pick ready", "data": payload}))

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
