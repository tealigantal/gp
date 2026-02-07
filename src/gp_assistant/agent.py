from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

from .config import AssistantConfig
from .session_store import SessionStore
from .index.store import IndexStore
from .state import SessionState, update_state_from_text, apply_defaults
from .repl_render import print_tool, print_exec, print_warn, render_user_prompt
from .tools.gpbt_runner import run_gpbt
from .tools.gp_runner import run_gp
from .tools.results_reader import summarize_run
from .tools.doctor_reader import read_doctor, summarize_doctor
from .tools.file_read import safe_read


SYS_PROMPT = (
    "你是仓库内的研究助手。回答前尽量基于仓库事实（README/configs/src/策略yaml/results）。"
    "当你声称‘读了某文件/执行某命令’，会话日志中必须包含相应的工具调用记录。"
    "仅允许受控动作：python gpbt.py / python gp.py 的白名单子命令，禁止任意 shell。"
    "优先 compare_strategies.csv / doctor_report.json / metrics.json；缺内容时建议下一步命令。"
)


class ChatAgent:
    def __init__(self, cfg: AssistantConfig):
        self.cfg = cfg
        self.repo = cfg.workspace_root
        self.sessions_dir = self.repo / 'store' / 'assistant' / 'sessions'
        self.session = SessionStore(self.sessions_dir)
        self.index = IndexStore(Path(cfg.rag.index_db))
        self.state = SessionState()
        self.print_state = False
        try:
            from .llm_client import SimpleLLMClient
            self.llm = SimpleLLMClient(cfg.llm.llm_config_file, {
                'temperature': cfg.llm.temperature,
                'max_tokens': cfg.llm.max_tokens,
                'timeout': cfg.llm.timeout,
            })
        except Exception:
            self.llm = None  # type: ignore

    def _gather_context(self, q: str) -> str:
        hits = self.index.search(q, topk=6)
        ctx = []
        for path, snip in hits:
            self.session.append('tool', 'repo_search', {'path': path, 'bytes': len(snip)})
            ctx.append(f"[FILE] {path}\n{snip}\n")
        if 'compare_strategies' in q.lower():
            txt = summarize_run(self.repo / 'results')
            if txt:
                self.session.append('tool', 'results_reader', {'summary_len': len(txt)})
                ctx.append("[RESULTS]\n" + txt)
        if 'doctor' in q.lower():
            rep = read_doctor(self.repo / 'results')
            summ = summarize_doctor(rep)
            if summ:
                self.session.append('tool', 'doctor_reader', {'keys': list(rep.get('checks', {}).keys()) if rep else []})
                ctx.append("[DOCTOR]\n" + summ)
        return "\n\n".join(ctx)

    def _chat_once(self, user: str) -> str:
        if self.llm is None:
            return 'LLM 未启用；请配置后再试或使用 “荐股” 指令。'
        ctx = self._gather_context(user)
        sys_msg = {'role': 'system', 'content': SYS_PROMPT}
        usr = {'role': 'user', 'content': f"问题：{user}\n\n上下文（可能不全）：\n{ctx}"}
        self.session.append('user', user)
        resp = self.llm.chat([sys_msg, usr], json_response=False)
        try:
            content = resp['choices'][0]['message']['content']
        except Exception:
            content = str(resp)
        self.session.append('assistant', content)
        return content

    def repl(self, *, print_text_only: bool = False, include_debug: bool = True) -> None:
        print_tool("ready: /help for commands (hidden by default)")
        while True:
            try:
                q = input(render_user_prompt()).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not q:
                continue
            delta = update_state_from_text(self.state, q)
            if delta:
                self.session.append('tool', 'state_update', delta)
                print_tool(f"state updated: {delta}")
            if q.startswith('/'):  # handle commands
                if self._handle_command(q):
                    continue
            resp = self.respond_json(q, include_debug=include_debug)
            if print_text_only:
                print(resp.get('text', ''))
            else:
                print(json.dumps(resp, ensure_ascii=False))

    def _handle_command(self, line: str) -> bool:
        import shlex
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ''
        if cmd in ['/help', '/h']:
            print_tool('/help, /state, /reset, /open <path>, /exec gpbt|gp <args>')
            return True
        if cmd == '/state':
            print_tool(getattr(self.state, 'summary', lambda: str(self.state))())
            return True
        if cmd == '/reset':
            self.state = SessionState()
            print_tool('state reset')
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
                tokens = shlex.split(arg)
                if not tokens:
                    print_warn('Usage: /exec gpbt|gp <subcmd> ...')
                    return True
                prog = tokens[0]
                sub = tokens[1] if len(tokens) > 1 else ''
                args = tokens[2:]
                if prog == 'gpbt':
                    code, out, err, dt = run_gpbt(sys.executable, self.repo, sub, args, self.cfg.tools.gpbt_allow_subcommands)
                    self.session.append('tool', 'gpbt', {'cmd': [sub] + args, 'code': code, 'stderr': err[:2000], 'seconds': dt})
                    if out:
                        print_exec(out)
                    if err:
                        print_warn(err)
                    return True
                if prog == 'gp':
                    code, out, err, dt = run_gp(sys.executable, self.repo, sub, args, self.cfg.tools.gp_allow_subcommands)
                    self.session.append('tool', 'gp', {'cmd': [sub] + args, 'code': code, 'stderr': err[:2000], 'seconds': dt})
                    if out:
                        print_exec(out)
                    if err:
                        print_warn(err)
                    return True
            except Exception as e:
                print_warn(str(e))
            return True
        return False

    def respond_json(self, user_text: str, *, include_debug: bool = True) -> Dict[str, Any]:
        raw = user_text
        plan = self._plan_intent(raw)
        intent = plan.get('intent', 'chat')
        req_date = plan.get('date')
        if not req_date:
            try:
                from datetime import datetime as _dt
                from .date_utils import parse_user_date
                d = parse_user_date(raw, _dt.now().date())
                if d is not None:
                    req_date = d.strftime('%Y%m%d')
            except Exception:
                req_date = None
        delta = update_state_from_text(self.state, raw)
        if delta:
            self.session.append('tool', 'state_update', delta)

        if intent == 'why_nth':
            import re as _re
            m = _re.search(r'(\d+)', raw)
            n = int(m.group(1)) if m else 1
            text = '暂无最近一次运行记录'
            run_id = getattr(self.state, 'last_run_id', None)
            if run_id:
                try:
                    p = self.repo / 'store' / 'pipeline_runs' / run_id / '05_final_response.json'
                    obj = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
                    recs = obj.get('recommendations', [])
                    if 1 <= n <= len(recs):
                        it = recs[n-1]
                        code = it.get('code') or ''
                        reason = it.get('thesis') or ''
                        text = f"第{n}只：{code} {reason}"
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
            from gp_core.pipeline import Pipeline as CorePipeline, PipelineConfig as CorePipelineConfig
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
            pipe = CorePipeline(
                self.repo,
                llm_cfg='configs/llm.yaml',
                search_cfg='configs/search.yaml',
                strategies_cfg=str(self.repo / 'configs' / 'strategies.yaml'),
                cfg=CorePipelineConfig(lookback_days=14, topk=profile['topk'], queries=['A股 两周市场摘要','指数 成交额 情绪','板块 轮动 热点'])
            )
            try:
                run_id, A, sel, runs, champ, resp = pipe.run(end_date=d2 or '', user_profile=profile, user_question=raw, topk=profile['topk'])
                self.state.default_date = d2
                self.state.last_run_id = run_id
                ftxt = self.repo / 'store' / 'pipeline_runs' / run_id / '05_final_response.txt'
                text = ftxt.read_text(encoding='utf-8') if ftxt.exists() else '已完成，但最终文本缺失。'
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
        t = str(user_text)
        if '/help' in t.lower():
            return {'intent': 'help'}
        if any(k in t for k in ['荐股','选股','股票','买哪个','买什么']) or any(k in t.lower() for k in ['recommend','pick','stock']):
            return {'intent': 'pick', 'date': None}
        import re as _re
        m = _re.search(r'(\d+)', t)
        if m and ('第' in t or any(ch in t for ch in ['#','No','no'])):
            return {'intent': 'why_nth', 'n': int(m.group(1))}
        if '为什么' in t and getattr(self.state, 'last_run_id', None):
            return {'intent': 'why_nth', 'n': 1}
        return {'intent': 'chat'}
