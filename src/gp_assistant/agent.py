from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List

from .config import AssistantConfig
from .llm_client import SimpleLLMClient
from .session_store import SessionStore
from .index.store import IndexStore
from .tools import repo_search
from .tools.gpbt_runner import run_gpbt
from .tools.doctor_reader import read_doctor
from .tools.results_reader import summarize_run
from .tools.file_read import safe_read
from .tools.run_registry import list_runs
from .index.store import IndexStore
from .session_store import SessionStore
from .config import AssistantConfig
from .llm_client import SimpleLLMClient
from .actions.pick import PickResult, pick_once
from .state import SessionState, update_state_from_text, apply_defaults
from .repl_render import print_agent, print_tool, print_exec, print_warn, render_user_prompt
from .date_utils import parse_user_date
from .tools.results_reader import summarize_run
from .tools.doctor_reader import read_doctor, summarize_doctor
from .tools.manifest_reader import read_manifest, summarize_manifest
from .tools.run_registry import list_runs
from .tools.file_read import safe_read
from .tools.gpbt_runner import run_gpbt
from .tools.gp_runner import run_gp


SYS_PROMPT = (
    "你是仓库内置的研究助手。回答前应尽量检索仓库事实（README、configs、src、策略yaml、results/）后作答。"\
    "当你声称‘我读了某文件 / 执行了某命令’，会话日志中必须包含对应的工具调用记录。"\
    "仅允许受控动作：python gpbt.py 与 python gp.py 的白名单子命令。禁止任意Shell。"\
    "优先基于 compare_strategies.csv、doctor_report.json、metrics.json 作答；缺内容时再建议下一步命令。"
)


class ChatAgent:
    def __init__(self, cfg: AssistantConfig):
        self.cfg = cfg
        self.repo = cfg.workspace_root
        self.sessions_dir = self.repo / 'store' / 'assistant' / 'sessions'
        self.session = SessionStore(self.sessions_dir)
        self.index = IndexStore(Path(cfg.rag.index_db))
        # Session state (per session only)
        self.state = SessionState()
        self.print_state = False
        # LLM may be optional (mock or disabled). Initialize defensively.
        try:
            self.llm = SimpleLLMClient(cfg.llm.llm_config_file, {
                'temperature': cfg.llm.temperature,
                'max_tokens': cfg.llm.max_tokens,
                'timeout': cfg.llm.timeout,
            })
        except Exception:
            # Defer hard failure; some actions (e.g., /pick) can run without LLM
            self.llm = None  # type: ignore

    def _gather_context(self, q: str) -> str:
        # Fulltext hits
        hits = self.index.search(q, topk=6)
        if not hits:
            # fallback to simple scan
            hits = repo_search.search(self.repo, q, self.cfg.rag.include_globs, self.cfg.rag.exclude_globs)
        ctx = []
        for path, snip in hits:
            self.session.append('tool', 'repo_search', {'path': path, 'bytes': len(snip)})
            ctx.append(f"[FILE] {path}\n{snip}\n")
        # Attach latest results summary if relevant
        if any(k in q.lower() for k in ['compare_strategies', '策略', '回测', '收益', '胜率']):
            txt = summarize_run(self.repo / 'results')
            if txt:
                self.session.append('tool', 'results_reader', {'summary_len': len(txt)})
                ctx.append("[RESULTS]\n" + txt)
        if any(k in q.lower() for k in ['doctor', '分钟', '缺失', '诊断']):
            rep = read_doctor(self.repo / 'results')
            summ = summarize_doctor(rep)
            if summ:
                self.session.append('tool', 'doctor_reader', {'keys': list(rep.get('checks', {}).keys()) if rep else []})
                ctx.append("[DOCTOR]\n" + summ)
        return "\n\n".join(ctx)

    def _chat_once(self, user: str) -> str:
        if self.llm is None:
            return 'LLM 未启用；请尝试使用 /pick 或输入“荐股”。'
        ctx = self._gather_context(user)
        sys_msg = {'role': 'system', 'content': SYS_PROMPT}
        usr = {'role': 'user', 'content': f"问题：{user}\n\n可用上下文（可能不全）：\n{ctx}"}
        self.session.append('user', user)
        resp = self.llm.chat([sys_msg, usr], json_response=False)
        try:
            content = resp['choices'][0]['message']['content']
        except Exception:
            content = str(resp)
        self.session.append('assistant', content)
        return content

    def repl(self, *, print_text_only: bool = False, include_debug: bool = True) -> None:
        # Interactive loop that prints a single JSON (or text) per user turn
        # 为保证前端对接，默认不打印欢迎语，保持一问一答的纯输出。
        print_tool("ready: /help for commands (hidden by default)")
        while True:
            try:
                q = input(render_user_prompt()).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not q:
                continue
            # Update state from natural text first（确定性解析，LLM planner 在 respond_json 内完成）
            delta = update_state_from_text(self.state, q)
            if delta:
                self.session.append('tool', 'state_update', delta)
                print_tool(f"state updated: date={delta.get('default_date','-')}, cash={delta.get('cash_available','-')}, positions={delta.get('positions',{}) if 'positions' in delta else '-'}, topk={delta.get('default_topk','-')}")
            if q.startswith('/'):
                handled = self._handle_command(q)
                if handled:
                    continue
            # Quick action shorthands
            if q.startswith('!gpbt '):
                self._run_gpbt_from_line(q[len('!gpbt '):])
                continue
            if q.startswith('!gp '):
                self._run_gp_from_line(q[len('!gp '):])
                continue
            # Quick follow-ups: exclude codes or toggle no_holdings
            if '排除' in q:
                import re as _re
                m = _re.search(r"排除\s*([0-9]{6}(?:\.(?:SZ|SH))?)", q)
                if m:
                    code = m.group(1)
                    if code not in self.state.exclusions:
                        self.state.exclusions.append(code)
                    print_tool(f'excluded: {code}')
                    # re-run pick if possible
                    if self.state.last_pick:
                        try:
                            res = pick_once(self.repo, self.session, date=self.state.default_date, topk=self.state.default_topk, template=self.state.default_template, mode=self.state.default_mode,
                                             positions=self.state.positions if self.state.no_holdings else None,
                                             cash=self.state.cash_available, exclusions=self.state.exclusions or None, no_holdings=self.state.no_holdings)
                            self.state.last_pick = {'date': res.date, 'mode': res.mode, 'provider': res.provider, 'ranked_list': res.ranked}
                            print_agent(self._format_pick_result(res))
                        except Exception as e:
                            print_warn(f'Pick failed: {e}')
                    continue
            if '只要非持仓' in q or '不要重复' in q:
                self.state.no_holdings = True
                print_tool('filter: no_holdings=true')
                if self.state.last_pick:
                    try:
                        res = pick_once(self.repo, self.session, date=self.state.default_date, topk=self.state.default_topk, template=self.state.default_template, mode=self.state.default_mode,
                                         positions=self.state.positions if self.state.no_holdings else None,
                                         cash=self.state.cash_available, exclusions=self.state.exclusions or None, no_holdings=self.state.no_holdings)
                        self.state.last_pick = {'date': res.date, 'mode': res.mode, 'provider': res.provider, 'ranked_list': res.ranked}
                        print_agent(self._format_pick_result(res))
                    except Exception as e:
                        print_warn(f'Pick failed: {e}')
                continue

            # Follow-up: Nth reason
            if '为什么' in q and ('第' in q or '第' in q):
                import re as _re
                m = _re.search(r"第\s*(\d+)\s*只", q)
                if not m:
                    m = _re.search(r"(\d+)号", q)
                if m and self.state.last_pick:
                    idx = int(m.group(1))
                    lst = self.state.last_pick.get('ranked_list', [])  # type: ignore
                    if 1 <= idx <= len(lst):
                        item = lst[idx-1]
                        reason = item.get('reasons') or item.get('reason') or ''
                        if isinstance(reason, list):
                            reason = ';'.join([str(x) for x in reason])
                        print_agent(f"第{idx}只 {item.get('ts_code')}: {reason}")
                        continue

            # Natural-language trigger for stock picking
            resp = self.respond_json(q, include_debug=include_debug)
            import json as _json
            if print_text_only:
                print(resp.get('text', ''))
            else:
                print(_json.dumps(resp, ensure_ascii=False))

    def _handle_command(self, line: str) -> bool:
        import shlex
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ''
        if cmd in ['/help', '/h']:
            print_tool('/help, /state, /reset, /exclude <code>, /include <code>, /runs, /run <id>, /doctor <id>, /open <path>, /exec gpbt|gp <args>')
            return True
        if cmd == '/runs':
            runs = list_runs(self.repo / 'results', limit=20)
            for r in runs:
                print_tool(f'- {r}')
            self.session.append('tool', 'runs_list', {'count': len(runs)})
            return True
        if cmd == '/run':
            rid = arg.strip()
            txt = summarize_run(self.repo / 'results', run_id=rid if rid else None)
            man = summarize_manifest(read_manifest(self.repo / 'results', run_id=rid if rid else None))
            if txt:
                print_tool(txt)
            if man:
                print_tool(man)
            self.session.append('tool', 'run_summary', {'id': rid or 'latest'})
            return True
        if cmd == '/doctor':
            rid = arg.strip() or None
            rep = read_doctor(self.repo / 'results', rid)
            print_tool(summarize_doctor(rep))
            self.session.append('tool', 'doctor_summary', {'id': rid or 'latest'})
            return True
        if cmd == '/open':
            p = arg.strip()
            try:
                content, n = safe_read(p, self.repo, allow_roots=[self.repo], max_bytes=2000)
                print_tool(content)
                self.session.append('tool', 'file_read', {'path': p, 'bytes': n})
            except Exception as e:
                print_warn(f'Error: {e}')
            return True
        if cmd == '/exec':
            try:
                # Expect: gpbt <subcmd> ... OR gp <subcmd> ...
                tokens = shlex.split(arg)
                if not tokens:
                    print_warn('Usage: /exec gpbt|gp <subcmd> ...')
                    return True
                prog = tokens[0]
                sub = tokens[1] if len(tokens) > 1 else ''
                args = tokens[2:]
                if prog == 'gpbt':
                    if sub not in self.cfg.tools.gpbt_allow_subcommands:
                        print_warn('Refused: not allowed. Allowed: ' + ','.join(self.cfg.tools.gpbt_allow_subcommands))
                        return True
                    code, out, err, dt = run_gpbt(sys.executable, self.repo, sub, args, self.cfg.tools.gpbt_allow_subcommands)
                    self.session.append('tool', 'gpbt', {'cmd': [sub] + args, 'code': code, 'stderr': err[:2000], 'seconds': dt})
                    if out:
                        print_exec(out)
                    if err:
                        print_warn(err)
                    return True
                if prog == 'gp':
                    if sub not in self.cfg.tools.gp_allow_subcommands:
                        print_warn('Refused: not allowed. Allowed: ' + ','.join(self.cfg.tools.gp_allow_subcommands))
                        return True
                    code, out, err, dt = run_gp(sys.executable, self.repo, sub, args, self.cfg.tools.gp_allow_subcommands)
                    self.session.append('tool', 'gp', {'cmd': [sub] + args, 'code': code, 'stderr': err[:2000], 'seconds': dt})
                    if out:
                        print_exec(out)
                    if err:
                        print_warn(err)
                    return True
                print_warn('Unknown program for /exec. Use gpbt or gp.')
            except Exception as e:
                print_warn(f'Error: {e}')
            return True
        if cmd == '/state':
            print_tool('state: ' + getattr(self, 'state').summary())
            return True
        if cmd == '/reset':
            self.state = SessionState()
            print_tool('state reset')
            return True
        if cmd == '/exclude':
            c = arg.strip()
            if c:
                if c not in self.state.exclusions:
                    self.state.exclusions.append(c)
                print_tool(f'excluded: {c}')
            if self.state.last_pick:
                try:
                    res = pick_once(self.repo, self.session, date=self.state.default_date, topk=self.state.default_topk, template=self.state.default_template, mode=self.state.default_mode,
                                     positions=self.state.positions if self.state.no_holdings else None,
                                     cash=self.state.cash_available,
                                     exclusions=self.state.exclusions or None,
                                     no_holdings=self.state.no_holdings)
                    self.state.last_pick = {'date': res.date, 'mode': res.mode, 'provider': res.provider, 'ranked_list': res.ranked}
                    print_agent(self._format_pick_result(res))
                except Exception as e:
                    print_warn(f'Pick failed: {e}')
            return True
        if cmd == '/include':
            c = arg.strip()
            if c and c in self.state.exclusions:
                self.state.exclusions = [x for x in self.state.exclusions if x != c]
                print_tool(f'included: {c}')
            return True
        if cmd == '/pick':
            # Usage: /pick [--date YYYYMMDD] [--topk K] [--template XXX] [--tier XXX]
            import shlex, argparse
            ap = argparse.ArgumentParser(prog='/pick', add_help=False)
            ap.add_argument('--date', dest='date', default=None)
            ap.add_argument('--topk', dest='topk', type=int, default=3)
            ap.add_argument('--template', dest='template', default='momentum_v1')
            ap.add_argument('--tier', dest='tier', default=None)
            ap.add_argument('--mode', dest='mode', default='auto', choices=['auto','llm'])
            try:
                ns, _ = ap.parse_known_args(shlex.split(arg))
            except SystemExit:
                print('Usage: /pick [--date YYYYMMDD] [--topk K] [--template XXX] [--tier XXX]')
                return True
            try:
                d2, k2, tpl2, md2 = apply_defaults(ns.date, ns.topk, ns.template, ns.mode, self.state)
                res = pick_once(self.repo, self.session, date=d2 or None, topk=k2, template=tpl2, tier=ns.tier, mode=md2,
                                 positions=self.state.positions if self.state.no_holdings else None,
                                 cash=self.state.cash_available,
                                 exclusions=self.state.exclusions or None,
                                 no_holdings=self.state.no_holdings)
                self.state.default_date = res.date
                self.state.last_pick = {'date': res.date, 'mode': res.mode, 'provider': res.provider, 'ranked_list': res.ranked}
                print_agent(self._format_pick_result(res))
            except Exception as e:
                print_warn(f'Pick failed: {e}')
            return True
        return False

    def _run_gpbt_from_line(self, line: str) -> None:
        parts = line.split()
        if not parts:
            return
        sub = parts[0]
        args = parts[1:]
        if sub not in self.cfg.tools.gpbt_allow_subcommands:
            print("Refused: not allowed. Allowed:", self.cfg.tools.gpbt_allow_subcommands)
            return
        code, out, err, dt = run_gpbt(sys.executable, self.repo, sub, args, self.cfg.tools.gpbt_allow_subcommands)
        self.session.append('tool', 'gpbt', {'cmd': [sub] + args, 'code': code, 'stderr': err[:2000], 'seconds': dt})
        if out:
            print_exec(out)
        if err:
            print_warn(err)

    def _run_gp_from_line(self, line: str) -> None:
        parts = line.split()
        if not parts:
            return
        sub = parts[0]
        args = parts[1:]
        if sub not in self.cfg.tools.gp_allow_subcommands:
            print("Refused: not allowed. Allowed:", self.cfg.tools.gp_allow_subcommands)
            return
        code, out, err, dt = run_gp(sys.executable, self.repo, sub, args, self.cfg.tools.gp_allow_subcommands)
        self.session.append('tool', 'gp', {'cmd': [sub] + args, 'code': code, 'stderr': err[:2000], 'seconds': dt})
        if out:
            print_exec(out)
        if err:
            print_warn(err)

    def results_summary_latest(self) -> str:
        return summarize_run(self.repo / 'results')

    def _format_pick_result(self, res: PickResult) -> str:
        items = []
        for r in res.ranked:
            reason = r.get('reasons', '') or r.get('reason', '') or ''
            if isinstance(reason, list):
                reason = ';'.join([str(x) for x in reason])
            hold_mark = ' [HOLDING]' if r.get('holding') else ''
            qty_sug = f" qty={r.get('suggest_qty')}" if r.get('suggest_qty') else ''
            items.append(f"{r.get('rank', '?')}. {r.get('ts_code')}{hold_mark}  {reason}{qty_sug}")
        status = res.data_status
        status_s = f"pool={'ok' if status.get('pool_ready') else 'missing'}; min5_gap={len(status.get('min5_missing', {}))}; daily_gap={len(status.get('daily_missing', {}))}"
        fallback_note = ''
        if res.provider in ('mock',):
            fallback_note = ' | LLM未启用/失败（使用 mock 补齐）'
        hdr = f"荐股 Top{res.topk}（{res.date} | 模板 {res.template} | 模式 {res.mode} | provider={res.provider}{fallback_note}）\n数据: {status_s}"
        return hdr + "\n" + "\n".join(items)

    def respond_json(self, user_text: str, *, include_debug: bool = True) -> Dict[str, Any]:
        """Build a single JSON response for a user_text according to schema gp.assistant.v1"""
        raw = user_text
        # 使用 LLM 做分流（planner）；失败时默认 pick（避免关键词 if 过拟合）
        plan = self._plan_intent(raw)
        intent = plan.get('intent', 'chat')
        req_date = plan.get('date')
        # Update state（资金/持仓/topk/排除/默认日期）已在 repl 前置解析，这里只采用 planner 的关键字段
        if not req_date:
            try:
                from datetime import datetime
                pd = parse_user_date(raw, datetime.now().date())
                if pd is not None:
                    req_date = pd.strftime('%Y%m%d')
            except Exception:
                req_date = None

        # Update state (cash/positions/topk/exclusions/date)
        delta = update_state_from_text(self.state, raw)
        if delta:
            self.session.append('tool', 'state_update', delta)

        if intent == 'why_nth' and self.state.last_pick:
            # extract number n
            import re as _re
            m = _re.search(r"第\s*(\d+)\s*只", raw)
            if not m:
                m = _re.search(r"(\d+)号", raw)
            n = int(m.group(1)) if m else 1
            lst = self.state.last_pick.get('ranked_list', [])  # type: ignore
            text = '暂无上一轮结果'
            if 1 <= n <= len(lst):
                item = lst[n-1]
                reason = item.get('reasons') or item.get('reason') or ''
                if isinstance(reason, list):
                    reason = ';'.join([str(x) for x in reason])
                text = f"第{n}只 {item.get('ts_code')}: {reason}"
            return {
                'schema_version': 'gp.assistant.v1',
                'type': 'chat',
                'ok': True,
                'request': {
                    'raw_user_text': raw,
                    'intent': 'why_nth',
                    'requested_date': req_date,
                    'topk': self.state.default_topk if hasattr(self.state,'default_topk') else 5,
                    'template': getattr(self.state, 'default_template', 'momentum_v1'),
                    'mode': getattr(self.state, 'default_mode', 'auto'),
                },
                'decision': {
                    'effective_date': self.state.last_pick.get('date') if isinstance(self.state.last_pick, dict) else None,
                    'fallback_reason': None,
                    'provider': self.state.last_pick.get('provider') if isinstance(self.state.last_pick, dict) else None,
                    'provider_reason': None,
                },
                'data_status': {},
                'portfolio_context': {
                    'cash_available': getattr(self.state, 'cash_available', None),
                    'positions': [{'code': k, 'shares': v} for k, v in getattr(self.state, 'positions', {}).items()],
                    'exclusions': list(getattr(self.state, 'exclusions', [])),
                },
                'recommendations': [],
                'text': text,
                'next_steps': [],
                'debug': None if not include_debug else {'tool_trace_digest': []},
            }

        # If user asks general "为什么" and we have last pick, summarize reasons instead of re-pick
        if ('为什么' in raw) and self.state.last_pick and intent not in ('why_nth', 'exclude'):
            lst = self.state.last_pick.get('ranked_list', []) if isinstance(self.state.last_pick, dict) else []
            lines = []
            for r in lst:
                why = r.get('reasons') or r.get('reason') or ''
                if isinstance(why, list):
                    why = ';'.join([str(x) for x in why])
                lines.append(f"{r.get('rank')}. {r.get('ts_code')} {why}")
            text = "上一轮荐股依据：\n" + ("\n".join(lines) if lines else '无可用记录')
            return {
                'schema_version': 'gp.assistant.v1',
                'type': 'chat',
                'ok': True,
                'request': {
                    'raw_user_text': raw,
                    'intent': 'why',
                    'requested_date': req_date,
                    'topk': getattr(self.state, 'default_topk', 3),
                    'template': getattr(self.state, 'default_template', 'momentum_v1'),
                    'mode': getattr(self.state, 'default_mode', 'auto'),
                },
                'decision': {
                    'effective_date': self.state.last_pick.get('date') if isinstance(self.state.last_pick, dict) else None,
                    'fallback_reason': None,
                    'provider': self.state.last_pick.get('provider') if isinstance(self.state.last_pick, dict) else None,
                    'provider_reason': None,
                },
                'data_status': {},
                'portfolio_context': {
                    'cash_available': getattr(self.state, 'cash_available', None),
                    'positions': [{'code': k, 'shares': v} for k, v in getattr(self.state, 'positions', {}).items()],
                    'exclusions': list(getattr(self.state, 'exclusions', [])),
                },
                'recommendations': [],
                'text': text,
                'next_steps': [],
                'debug': None if not include_debug else {'tool_trace_digest': []},
            }

        if intent == 'pick':
            # Use defaults
            d2, k2, tpl2, md2 = apply_defaults(req_date, None, None, None, self.state)
            try:
                res = pick_once(self.repo, self.session, date=d2 or None, topk=k2, template=tpl2, mode=md2,
                                positions=self.state.positions if getattr(self.state,'no_holdings',False) else None,
                                cash=getattr(self.state,'cash_available',None), exclusions=getattr(self.state,'exclusions',None),
                                no_holdings=getattr(self.state,'no_holdings',False))
                # Update state
                self.state.default_date = res.date
                self.state.last_pick = {'date': res.date, 'mode': res.mode, 'provider': res.provider, 'ranked_list': res.ranked}
                # Build JSON
                recs = []
                for r in res.ranked:
                    why = r.get('reasons')
                    if isinstance(why, str):
                        why_list = [why] if why else []
                    else:
                        why_list = list(why or [])
                    recs.append({
                        'rank': int(r.get('rank', 0) or 0),
                        'code': str(r.get('ts_code','')),
                        'name': None,
                        'action': 'BUY',
                        'score': float(r.get('score', 0.0) or 0.0),
                        'confidence': float(r.get('confidence', 0.0) or 0.0),
                        'suggested_order': {'shares': int(r.get('suggest_qty', 0) or 0), 'est_price': None},
                        'why': why_list,
                        'risk_flags': [],
                    })
                status = res.data_status
                # daily missing -> risk flag
                daily_missing_codes = list(status.get('daily_missing', []) or [])
                if daily_missing_codes:
                    for x in recs:
                        # just annotate overall
                        x['risk_flags'].append('DATA_GAP')
                min5_pairs = 0
                mm = status.get('min5_missing', {}) or {}
                if isinstance(mm, dict):
                    min5_pairs = sum(len(v) for v in mm.values())
                    if min5_pairs:
                        for x in recs:
                            x['risk_flags'].append('MIN5_MISSING')

                text = self._build_pick_text(res)
                debug = None
                if include_debug:
                    debug = {'tool_trace_digest': res.trace}
                return {
                    'schema_version': 'gp.assistant.v1',
                    'type': 'pick',
                    'ok': True,
                    'request': {
                        'raw_user_text': raw,
                        'intent': 'pick',
                        'requested_date': res.requested_date,
                        'topk': res.topk,
                        'template': res.template,
                        'mode': res.mode,
                    },
                    'decision': {
                        'effective_date': res.date,
                        'fallback_reason': res.fallback_reason,
                        'provider': res.provider,
                        'provider_reason': ('LLM 排序成功（候选池已校验）' if res.provider == 'llm' else 'LLM 不可用/失败，已使用 mock 进行补齐与排序'),
                    },
                    'data_status': {
                        'pool_path': str((self.repo / 'universe' / f"candidate_pool_{res.date}.csv")),
                        'pool_count': int(status.get('pool_count', 0) or 0),
                        'daily_missing_codes': daily_missing_codes,
                        'min5_missing_pairs_count': int(min5_pairs),
                        'meta_missing_days': [],
                        'doctor_status': None,
                    },
                    'portfolio_context': {
                        'cash_available': getattr(self.state, 'cash_available', None),
                        'positions': [{'code': k, 'shares': v} for k, v in getattr(self.state, 'positions', {}).items()],
                        'exclusions': list(getattr(self.state, 'exclusions', [])),
                    },
                    'recommendations': recs,
                    'text': text,
                    'next_steps': [],
                    'debug': debug,
                }
            except Exception as e:
                # Return an error JSON, never crash
                return {
                    'schema_version': 'gp.assistant.v1',
                    'type': 'error',
                    'ok': False,
                    'request': {
                        'raw_user_text': raw,
                        'intent': 'pick',
                        'requested_date': req_date,
                        'topk': getattr(self.state, 'default_topk', 5),
                        'template': getattr(self.state, 'default_template', 'momentum_v1'),
                        'mode': getattr(self.state, 'default_mode', 'auto'),
                    },
                    'decision': {'effective_date': None, 'fallback_reason': str(e), 'provider': None, 'provider_reason': 'pick failed: exception'},
                    'data_status': {},
                    'portfolio_context': {
                        'cash_available': getattr(self.state, 'cash_available', None),
                        'positions': [{'code': k, 'shares': v} for k, v in getattr(self.state, 'positions', {}).items()],
                        'exclusions': list(getattr(self.state, 'exclusions', [])),
                    },
                    'recommendations': [],
                    'text': f'发生错误：{e}。建议先修复数据或配置后再试。',
                    'next_steps': [
                        'python gpbt.py init',
                        'python gpbt.py fetch --start YYYYMMDD --end YYYYMMDD --no-minutes',
                        'python gpbt.py build-candidates --date YYYYMMDD',
                        'python gpbt.py doctor --start YYYYMMDD --end YYYYMMDD'
                    ],
                    'debug': None if not include_debug else {'tool_trace_digest': []},
                }

        # default chat (robust: never crash on LLM/proxy errors)
        try:
            s = self._chat_once(raw)
            ok = True
            fallback = None
        except Exception as e:
            s = (
                "对话模型不可用：已保底为‘荐股’通道可用。你可以直接输入‘荐股’或‘20260209荐股’继续使用自动选股。"
                "如走直连 DeepSeek，请在环境中设置 DEEPSEEK_API_KEY，并将 configs/llm.yaml 的 base_url 设为 https://api.deepseek.com/v1；"
                "如走 llm-proxy，请设置 UPSTREAM_API_KEY（代理读取此变量转发）。"
            )
            ok = False
            fallback = str(e)
        return {
            'schema_version': 'gp.assistant.v1',
            'type': 'chat',
            'ok': ok,
            'request': {'raw_user_text': raw, 'intent': 'chat', 'requested_date': req_date, 'topk': getattr(self.state,'default_topk',5), 'template': getattr(self.state,'default_template','momentum_v1'), 'mode': getattr(self.state,'default_mode','auto')},
            'decision': {'effective_date': None, 'fallback_reason': fallback, 'provider': None, 'provider_reason': None},
            'data_status': {},
            'portfolio_context': {'cash_available': getattr(self.state,'cash_available',None), 'positions': [{'code': k, 'shares': v} for k,v in getattr(self.state,'positions',{}).items()], 'exclusions': list(getattr(self.state,'exclusions',[]))},
            'recommendations': [],
            'text': s,
            'next_steps': [
                'export DEEPSEEK_API_KEY=sk-... 或设置 UPSTREAM_API_KEY',
                '检查 configs/llm.yaml 中 provider/base_url/model 设置',
                'assistant chat --once "20260209荐股" 以走荐股通道'
            ],
            'debug': None if not include_debug else {'tool_trace_digest': []},
        }

    def _plan_intent(self, user_text: str) -> Dict[str, Any]:
        """Planner-first routing. Try LLM to classify intent; fallback to keyword router only for intent (no rule-based ranking).
        返回 dict: {intent, date, topk, template, mode, exclude, why_n}
        """
        import json as _json
        # Prefer LLM planner if available
        if self.llm is not None:
            state_summary = {
                'date': getattr(self.state, 'default_date', None),
                'topk': getattr(self.state, 'default_topk', 5) if hasattr(self.state, 'default_topk') else 5,
                'template': getattr(self.state, 'default_template', 'momentum_v1'),
                'mode': getattr(self.state, 'default_mode', 'auto'),
                'positions': list(getattr(self.state, 'positions', {}).keys()),
                'exclusions': list(getattr(self.state, 'exclusions', [])),
            }
            sys_prompt = (
                "你是参数规划器，只返回一个 JSON（不要多余文本）。\n"
                "字段: intent(pick|chat|why_nth|exclude|help), date(YYYYMMDD|null), topk(int|null), template(momentum_v1|pullback_v1|defensive_v1|null), mode(auto|llm|null), exclude([codes]), why_n(int|null)。\n"
                "只负责分流，不进行任何排序或业务决策。无法判断时输出 intent=chat。"
            )
            content = {'user_text': user_text, 'state': state_summary}
            try:
                msgs = [
                    {'role': 'system', 'content': sys_prompt},
                    {'role': 'user', 'content': _json.dumps(content, ensure_ascii=False)}
                ]
                resp = self.llm.chat(msgs, json_response=True)
                txt = resp.get('choices', [{}])[0].get('message', {}).get('content', '{}')
                obj = _json.loads(txt)
                if isinstance(obj, dict) and obj.get('intent'):
                    return obj
            except Exception:
                pass
        # Keyword-only fallback router
        t = str(user_text)
        # why nth
        import re as _re
        why_n = None
        m = _re.search(r"第\s*(\d+)\s*只", t)
        if not m:
            m = _re.search(r"(\d+)号", t)
        if m:
            try:
                why_n = int(m.group(1))
            except Exception:
                why_n = None
        # exclude codes
        ex_codes: List[str] = []
        for m2 in _re.finditer(r"排除\s*([0-9]{6}(?:\.(?:SZ|SH))?)", t):
            ex_codes.append(m2.group(1))
        if 'help' in t.lower() or '/help' in t.lower() or '帮助' in t:
            intent = 'help'
        elif why_n is not None:
            intent = 'why_nth'
        elif any(k in t for k in ['荐股','选股','股票','买什么','pick']):
            # 如果包含“为什么”，优先按问答处理，避免误触发荐股
            if '为什么' in t:
                intent = 'chat'
            else:
                intent = 'pick'
        elif ex_codes:
            intent = 'exclude'
        else:
            intent = 'chat'
        return {'intent': intent, 'date': None, 'topk': None, 'template': None, 'mode': None, 'exclude': ex_codes, 'why_n': why_n}

    def _build_pick_text(self, res: PickResult) -> str:
        status = res.data_status
        parts = []
        rq = res.requested_date
        # First line: concise outcome + provider explanation
        provider_note = '（LLM 排序）' if res.provider == 'llm' else '（LLM 不可用/失败 → 使用 mock 补齐，仅作演示）'
        head = f"日期：{res.date} {provider_note}"
        if rq and rq != res.date:
            head += f"（requested={rq}，已回退）"
        parts.append(head)
        # data gaps
        daily_missing = status.get('daily_missing', []) or []
        mm = status.get('min5_missing', {}) or {}
        miss = []
        if daily_missing:
            miss.append(f"日线缺失{len(daily_missing)}只")
        if isinstance(mm, dict):
            pairs = sum(len(v) for v in mm.values())
            if pairs:
                miss.append(f"分钟缺失{pairs}对")
        if miss:
            parts.append("数据缺口：" + ",".join(miss))
        # provider and mode
        parts.append(f"策略：template={res.template} mode={res.mode} provider={res.provider}")
        # TopK summary
        lines = []
        for r in res.ranked:
            why = r.get('reasons')
            if isinstance(why, list):
                why = ';'.join([str(x) for x in why])
            lines.append(f"{r.get('rank')}. {r.get('ts_code')} {why or ''}")
        parts.append("TopK：\n" + "\n".join(lines))
        parts.append("操作与风险：建议100股整数倍，非下单指令；关注数据缺口与分钟线风险。")
        return "\n".join(parts)
