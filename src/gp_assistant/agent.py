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

    def repl(self) -> None:
        print("Repo assistant ready. Type /help for commands. Ctrl+C to exit.")
        while True:
            try:
                q = input('>>> ').strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not q:
                continue
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
            # Natural-language trigger for stock picking
            if any(k in q for k in ['荐股', '推荐', '选股', 'topk', 'TopK', 'TOPK']):
                try:
                    res = pick_once(self.repo, self.session, date=None, topk=3, template='momentum_v1')
                    print(self._format_pick_result(res))
                except Exception as e:
                    print('Pick failed:', e)
                continue
            ans = self._chat_once(q)
            print(ans)

    def _handle_command(self, line: str) -> bool:
        import shlex
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ''
        if cmd in ['/help', '/h']:
            print('/help, /runs, /run <id>, /doctor <id>, /open <path>, /exec gpbt|gp <args>')
            return True
        if cmd == '/runs':
            runs = list_runs(self.repo / 'results', limit=20)
            for r in runs:
                print('-', r)
            self.session.append('tool', 'runs_list', {'count': len(runs)})
            return True
        if cmd == '/run':
            rid = arg.strip()
            txt = summarize_run(self.repo / 'results', run_id=rid if rid else None)
            man = summarize_manifest(read_manifest(self.repo / 'results', run_id=rid if rid else None))
            print(txt)
            print(man)
            self.session.append('tool', 'run_summary', {'id': rid or 'latest'})
            return True
        if cmd == '/doctor':
            rid = arg.strip() or None
            rep = read_doctor(self.repo / 'results', rid)
            print(summarize_doctor(rep))
            self.session.append('tool', 'doctor_summary', {'id': rid or 'latest'})
            return True
        if cmd == '/open':
            p = arg.strip()
            try:
                content, n = safe_read(p, self.repo, allow_roots=[self.repo], max_bytes=2000)
                print(content)
                self.session.append('tool', 'file_read', {'path': p, 'bytes': n})
            except Exception as e:
                print('Error:', e)
            return True
        if cmd == '/exec':
            try:
                # Expect: gpbt <subcmd> ... OR gp <subcmd> ...
                tokens = shlex.split(arg)
                if not tokens:
                    print('Usage: /exec gpbt|gp <subcmd> ...')
                    return True
                prog = tokens[0]
                sub = tokens[1] if len(tokens) > 1 else ''
                args = tokens[2:]
                if prog == 'gpbt':
                    if sub not in self.cfg.tools.gpbt_allow_subcommands:
                        print('Refused: not allowed. Allowed:', self.cfg.tools.gpbt_allow_subcommands)
                        return True
                    code, out, err, dt = run_gpbt(sys.executable, self.repo, sub, args, self.cfg.tools.gpbt_allow_subcommands)
                    self.session.append('tool', 'gpbt', {'cmd': [sub] + args, 'code': code, 'stderr': err[:2000], 'seconds': dt})
                    print(out)
                    if err:
                        print(err, file=sys.stderr)
                    return True
                if prog == 'gp':
                    if sub not in self.cfg.tools.gp_allow_subcommands:
                        print('Refused: not allowed. Allowed:', self.cfg.tools.gp_allow_subcommands)
                        return True
                    code, out, err, dt = run_gp(sys.executable, self.repo, sub, args, self.cfg.tools.gp_allow_subcommands)
                    self.session.append('tool', 'gp', {'cmd': [sub] + args, 'code': code, 'stderr': err[:2000], 'seconds': dt})
                    print(out)
                    if err:
                        print(err, file=sys.stderr)
                    return True
                print('Unknown program for /exec. Use gpbt or gp.')
            except Exception as e:
                print('Error:', e)
            return True
        if cmd == '/pick':
            # Usage: /pick [--date YYYYMMDD] [--topk K] [--template XXX] [--tier XXX]
            import shlex, argparse
            ap = argparse.ArgumentParser(prog='/pick', add_help=False)
            ap.add_argument('--date', dest='date', default=None)
            ap.add_argument('--topk', dest='topk', type=int, default=3)
            ap.add_argument('--template', dest='template', default='momentum_v1')
            ap.add_argument('--tier', dest='tier', default=None)
            try:
                ns, _ = ap.parse_known_args(shlex.split(arg))
            except SystemExit:
                print('Usage: /pick [--date YYYYMMDD] [--topk K] [--template XXX] [--tier XXX]')
                return True
            try:
                res = pick_once(self.repo, self.session, date=ns.date, topk=ns.topk, template=ns.template, tier=ns.tier)
                print(self._format_pick_result(res))
            except Exception as e:
                print('Pick failed:', e)
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
        print(out)
        if err:
            print(err, file=sys.stderr)

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
        print(out)
        if err:
            print(err, file=sys.stderr)

    def results_summary_latest(self) -> str:
        return summarize_run(self.repo / 'results')

    def _format_pick_result(self, res: PickResult) -> str:
        items = []
        for r in res.ranked:
            reason = r.get('reasons', '') or r.get('reason', '') or ''
            if isinstance(reason, list):
                reason = ';'.join([str(x) for x in reason])
            items.append(f"{r.get('rank', '?')}. {r.get('ts_code')}  {reason}")
        status = res.data_status
        status_s = f"pool={'ok' if status.get('pool_ready') else 'missing'}; min5_gap={len(status.get('min5_missing', {}))}; daily_gap={len(status.get('daily_missing', {}))}"
        hdr = f"荐股 Top{res.topk}（{res.date} | 模板 {res.template} | provider={res.provider}）\n数据: {status_s}"
        return hdr + "\n" + "\n".join(items)
