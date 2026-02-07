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
from gp_core.pipeline import Pipeline as CorePipeline, PipelineConfig as CorePipelineConfig


SYS_PROMPT = (
    "浣犳槸浠撳簱鍐呯疆鐨勭爺绌跺姪鎵嬨€傚洖绛斿墠搴斿敖閲忔绱粨搴撲簨瀹烇紙README銆乧onfigs銆乻rc銆佺瓥鐣aml銆乺esults/锛夊悗浣滅瓟銆?\
    "褰撲綘澹扮О鈥樻垜璇讳簡鏌愭枃浠?/ 鎵ц浜嗘煇鍛戒护鈥欙紝浼氳瘽鏃ュ織涓繀椤诲寘鍚搴旂殑宸ュ叿璋冪敤璁板綍銆?\
    "浠呭厑璁稿彈鎺у姩浣滐細python gpbt.py 涓?python gp.py 鐨勭櫧鍚嶅崟瀛愬懡浠ゃ€傜姝换鎰廠hell銆?\
    "浼樺厛鍩轰簬 compare_strategies.csv銆乨octor_report.json銆乵etrics.json 浣滅瓟锛涚己鍐呭鏃跺啀寤鸿涓嬩竴姝ュ懡浠ゃ€?
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
        if any(k in q.lower() for k in ['compare_strategies', '绛栫暐', '鍥炴祴', '鏀剁泭', '鑳滅巼']):
            txt = summarize_run(self.repo / 'results')
            if txt:
                self.session.append('tool', 'results_reader', {'summary_len': len(txt)})
                ctx.append("[RESULTS]\n" + txt)
        if any(k in q.lower() for k in ['doctor', '鍒嗛挓', '缂哄け', '璇婃柇']):
            rep = read_doctor(self.repo / 'results')
            summ = summarize_doctor(rep)
            if summ:
                self.session.append('tool', 'doctor_reader', {'keys': list(rep.get('checks', {}).keys()) if rep else []})
                ctx.append("[DOCTOR]\n" + summ)
        return "\n\n".join(ctx)

    def _chat_once(self, user: str) -> str:
        if self.llm is None:
            return 'LLM 鏈惎鐢紱璇峰皾璇曚娇鐢?/pick 鎴栬緭鍏モ€滆崘鑲♀€濄€?
        ctx = self._gather_context(user)
        sys_msg = {'role': 'system', 'content': SYS_PROMPT}
        usr = {'role': 'user', 'content': f"闂锛歿user}\n\n鍙敤涓婁笅鏂囷紙鍙兘涓嶅叏锛夛細\n{ctx}"}
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
        # 涓轰繚璇佸墠绔鎺ワ紝榛樿涓嶆墦鍗版杩庤锛屼繚鎸佷竴闂竴绛旂殑绾緭鍑恒€?        print_tool("ready: /help for commands (hidden by default)")
        while True:
            try:
                q = input(render_user_prompt()).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not q:
                continue
            # Update state from natural text first锛堢‘瀹氭€цВ鏋愶紝LLM planner 鍦?respond_json 鍐呭畬鎴愶級
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
            if '鎺掗櫎' in q:
                import re as _re
                m = _re.search(r"鎺掗櫎\s*([0-9]{6}(?:\.(?:SZ|SH))?)", q)
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
            if '鍙闈炴寔浠? in q or '涓嶈閲嶅' in q:
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
            if '涓轰粈涔? in q and ('绗? in q or '绗? in q):
                import re as _re
                m = _re.search(r"绗琝s*(\d+)\s*鍙?, q)
                if not m:
                    m = _re.search(r"(\d+)鍙?, q)
                if m and self.state.last_pick:
                    idx = int(m.group(1))
                    lst = self.state.last_pick.get('ranked_list', [])  # type: ignore
                    if 1 <= idx <= len(lst):
                        item = lst[idx-1]
                        reason = item.get('reasons') or item.get('reason') or ''
                        if isinstance(reason, list):
                            reason = ';'.join([str(x) for x in reason])
                        print_agent(f"绗瑊idx}鍙?{item.get('ts_code')}: {reason}")
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
        if cmd in ['/pref', '/profile']:
            # Usage: /pref risk=conservative style=trend topk=3 universe=A鑲?            kvs = {}
            for tok in arg.split():
                if '=' in tok:
                    k, v = tok.split('=', 1)
                    kvs[k.strip().lower()] = v.strip()
            if 'risk' in kvs:
                self.state.risk_pref = kvs['risk']
            if 'topk' in kvs:
                try:
                    self.state.default_topk = int(kvs['topk'])
                except Exception:
                    pass
            if 'template' in kvs:
                self.state.default_template = kvs['template']
            if 'mode' in kvs:
                self.state.default_mode = kvs['mode']
            print_tool(f"profile updated: {self.state.summary()}")
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
        hdr = f"荐股 Top{res.topk}（{res.date} | 模板 {res.template} | 模式 {res.mode} | provider={res.provider}）\n数据: {status_s}"
        return hdr + "\n" + "\n".join(items)
            if run_id:
                try:
                    p = self.repo / 'store' / 'pipeline_runs' / run_id / '05_final_response.json'
                    obj = _json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
                    recs = obj.get('recommendations', [])
                    if 1 <= n <= len(recs):
                        it = recs[n-1]
                        code = it.get('code') or ''
                        reason = it.get('thesis') or ''
                        text = f"第{n}：{code} {reason}"
                except Exception:
                    pass
            return {
                'schema_version': 'gp.assistant.v1',
                'type': 'chat',
                'ok': True,
                'request': {'raw_user_text': raw, 'intent': 'why_nth', 'requested_date': req_date, 'topk': getattr(self.state,'default_topk',5), 'template': getattr(self.state, 'default_template', 'momentum_v1'), 'mode': getattr(self.state,'default_mode','auto')},
                'decision': {'effective_date': getattr(self.state,'default_date',None), 'fallback_reason': None, 'provider': 'pipeline', 'provider_reason': 'read-artifacts'},
                'data_status': {},
                'portfolio_context': {'cash_available': getattr(self.state,'cash_available',None), 'positions': [{'code': k, 'shares': v} for k, v in getattr(self.state, 'positions', {}).items()], 'exclusions': list(getattr(self.state, 'exclusions', []))},
                'recommendations': [],
                'text': text,
                'next_steps': [],
                'debug': None if not include_debug else {'tool_trace_digest': []},
            }

        if intent == 'pick':
            d2, _, _, _ = apply_defaults(req_date, None, None, None, self.state)
            profile = {
                'risk_level': getattr(self.state, 'risk_pref', None) or 'neutral',
                'style_preference': None,
                'universe': 'A股',
                'max_positions': int(getattr(self.state, 'default_topk', 3) or 3),
                'sector_preference': [],
                'max_drawdown_tolerance': None,
                'topk': int(getattr(self.state, 'default_topk', 3) or 3),
            }
            from gp_core.pipeline import Pipeline as CorePipeline, PipelineConfig as CorePipelineConfig
            pipe = CorePipeline(self.repo, llm_cfg='configs/llm.yaml', search_cfg='configs/search.yaml', strategies_cfg=str(self.repo / 'configs' / 'strategies.yaml'), cfg=CorePipelineConfig(lookback_days=14, topk=profile['topk'], queries=['A股 市场 两周 摘要','指数 成交额 情绪','板块 轮动 热点']))
            try:
                run_id, A, sel, runs, champ, resp = pipe.run(end_date=d2 or '', user_profile=profile, user_question=raw, topk=profile['topk'])
                self.state.default_date = d2
                self.state.last_run_id = run_id
                ftxt = self.repo / 'store' / 'pipeline_runs' / run_id / '05_final_response.txt'
                text = ftxt.read_text(encoding='utf-8') if ftxt.exists() else '完成，但缺少最终文本输出文件。'
                return {
                    'schema_version': 'gp.assistant.v1',
                    'type': 'pick',
                    'ok': True,
                    'request': {'raw_user_text': raw, 'intent': 'pick', 'requested_date': d2, 'topk': profile['topk'], 'template': None, 'mode': 'pipeline'},
                    'decision': {'effective_date': d2, 'fallback_reason': None, 'provider': 'llm', 'provider_reason': 'pipeline'},
                    'data_status': {},
                    'portfolio_context': {'cash_available': getattr(self.state,'cash_available',None), 'positions': [{'code': k, 'shares': v} for k,v in getattr(self.state,'positions',{}).items()], 'exclusions': list(getattr(self.state,'exclusions',[]))},
                    'recommendations': [],
                    'text': text,
                    'next_steps': [],
                    'debug': None,
                }
            except Exception as e:
                return {
                    'schema_version': 'gp.assistant.v1',
                    'type': 'error',
                    'ok': False,
                    'request': {'raw_user_text': raw, 'intent': 'pick', 'requested_date': d2, 'topk': profile['topk'], 'template': None, 'mode': 'pipeline'},
                    'decision': {'effective_date': None, 'fallback_reason': str(e), 'provider': None, 'provider_reason': 'pipeline error'},
                    'data_status': {},
                    'portfolio_context': {'cash_available': getattr(self.state,'cash_available',None), 'positions': [{'code': k, 'shares': v} for k,v in getattr(self.state,'positions',{}).items()], 'exclusions': list(getattr(self.state,'exclusions',[]))},
                    'recommendations': [],
                    'text': f'发生错误：{e}',
                    'next_steps': [],
                    'debug': None,
                }

        # default chat
        try:
            s = self._chat_once(raw)
            ok = True
            fallback = None
        except Exception as e:
            s = '对话模型不可用，请配置 LLM Key 后重试。'
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
            'next_steps': [],
            'debug': None if not include_debug else {'tool_trace_digest': []},
        }
    def _plan_intent(self, user_text: str) -> Dict[str, Any]:
        """Planner-first routing. Try LLM to classify intent; fallback to keyword router only for intent (no rule-based ranking).
        杩斿洖 dict: {intent, date, topk, template, mode, exclude, why_n}
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
                "浣犳槸鍙傛暟瑙勫垝鍣紝鍙繑鍥炰竴涓?JSON锛堜笉瑕佸浣欐枃鏈級銆俓n"
                "瀛楁: intent(pick|chat|why_nth|exclude|help), date(YYYYMMDD|null), topk(int|null), template(momentum_v1|pullback_v1|defensive_v1|null), mode(auto|llm|null), exclude([codes]), why_n(int|null)銆俓n"
                "鍙礋璐ｅ垎娴侊紝涓嶈繘琛屼换浣曟帓搴忔垨涓氬姟鍐崇瓥銆傛棤娉曞垽鏂椂杈撳嚭 intent=chat銆?
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
        m = _re.search(r"绗琝s*(\d+)\s*鍙?, t)
        if not m:
            m = _re.search(r"(\d+)鍙?, t)
        if m:
            try:
                why_n = int(m.group(1))
            except Exception:
                why_n = None
        # exclude codes
        ex_codes: List[str] = []
        for m2 in _re.finditer(r"鎺掗櫎\s*([0-9]{6}(?:\.(?:SZ|SH))?)", t):
            ex_codes.append(m2.group(1))
        if 'help' in t.lower() or '/help' in t.lower() or '甯姪' in t:
            intent = 'help'
        elif why_n is not None:
            intent = 'why_nth'
        elif any(k in t for k in ['鑽愯偂','閫夎偂','鑲＄エ','涔颁粈涔?,'pick']):
            # 濡傛灉鍖呭惈鈥滀负浠€涔堚€濓紝浼樺厛鎸夐棶绛斿鐞嗭紝閬垮厤璇Е鍙戣崘鑲?            if '涓轰粈涔? in t:
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
        provider_note = '锛圠LM 鎺掑簭锛? if res.provider == 'llm' else '锛圠LM 涓嶅彲鐢?澶辫触 鈫?浣跨敤 mock 琛ラ綈锛屼粎浣滄紨绀猴級'
        head = f"鏃ユ湡锛歿res.date} {provider_note}"
        if rq and rq != res.date:
            head += f"锛坮equested={rq}锛屽凡鍥為€€锛?
        parts.append(head)
        # data gaps
        daily_missing = status.get('daily_missing', []) or []
        mm = status.get('min5_missing', {}) or {}
        miss = []
        if daily_missing:
            miss.append(f"鏃ョ嚎缂哄け{len(daily_missing)}鍙?)
        if isinstance(mm, dict):
            pairs = sum(len(v) for v in mm.values())
            if pairs:
                miss.append(f"鍒嗛挓缂哄け{pairs}瀵?)
        if miss:
            parts.append("鏁版嵁缂哄彛锛? + ",".join(miss))
        # provider and mode
        parts.append(f"绛栫暐锛歵emplate={res.template} mode={res.mode} provider={res.provider}")
        # TopK summary
        lines = []
        for r in res.ranked:
            why = r.get('reasons')
            if isinstance(why, list):
                why = ';'.join([str(x) for x in why])
            lines.append(f"{r.get('rank')}. {r.get('ts_code')} {why or ''}")
        parts.append("TopK锛歕n" + "\n".join(lines))
        parts.append("鎿嶄綔涓庨闄╋細寤鸿100鑲℃暣鏁板€嶏紝闈炰笅鍗曟寚浠わ紱鍏虫敞鏁版嵁缂哄彛涓庡垎閽熺嚎椋庨櫓銆?)
        return "\n".join(parts)
