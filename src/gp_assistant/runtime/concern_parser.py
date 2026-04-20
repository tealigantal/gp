from __future__ import annotations

from typing import Any, Dict

from .context_engine import build_context
from ..llm.interpret import parse_turn_frame
from ..contracts.objects import MarketBook, TurnFrame
from ..runtime.utils import gen_id
from typing import Any, Dict


def _extract_rank_from_zh(s: str) -> int | None:
    s = (s or '').strip()
    # Simple patterns: 第一只/第二只/第三只/第N只
    mapping = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5}
    for zh, n in mapping.items():
        if f'第{zh}只' in s or f'第{zh}' in s:
            return n
    # Arabic form: 第2只
    import re
    m = re.search(r'第\s*(\d{1,2})\s*只', s)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def _inject_reference_hints(frame: TurnFrame, memory_ctx: Dict[str, Any], book: MarketBook) -> TurnFrame:
    refs = dict(frame.references or {})
    raw = (frame.raw_message or '').strip()
    session = memory_ctx['session']
    # Resolve "这只/这个票" to focus symbol when available
    if any(k in raw for k in ['这只', '这个票', '该票']) and isinstance(session.focus_subject, dict):
        if not refs.get('symbol') and session.focus_subject.get('type') == 'symbol':
            sym = session.focus_subject.get('symbol')
            if isinstance(sym, str) and sym:
                refs['symbol'] = sym
    # Chinese ordinal -> rank reference
    if refs.get('rank') is None:
        rk = _extract_rank_from_zh(raw)
        if rk is not None:
            refs['rank'] = rk
    frame.references = refs
    return frame


def _quick_rule_parse(memory_ctx: Dict[str, Any], book: MarketBook, user_message: str) -> TurnFrame | None:
    """Deterministic fast-path for common intents to reduce LLM dependency.

    Patterns:
    - 今天给我X只 => recommend run, topk=X
    - 为什么空仓 => explain run
    - 第二只为什么 / 第N只 => explain pick, rank=N
    - (?P<sym>code).*止损|止盈|卖|减仓 => exit symbol
    - 现在还能买/盘中.*看 => live_check (symbol from pronoun/focus best-effort)
    """
    msg = (user_message or '').strip()
    if not msg:
        return None
    import re
    frame: Dict[str, Any] | None = None
    # 今天给我 X 只
    m = re.search(r"今天给我\s*(\d{1,2})\s*只", msg)
    if m:
        try:
            k = int(m.group(1))
        except Exception:
            k = 3
        frame = {
            'frame_id': gen_id('frame'),
            'raw_message': user_message,
            'subject': 'run',
            'request': 'recommend',
            'freshness': 'current_book',
            'references': {},
            'constraints': {'topk': k},
            'ambiguity': {'confidence': 0.95, 'notes': []},
        }
        return TurnFrame.model_validate(frame)
    # 为什么空仓
    if '空仓' in msg and ('为什么' in msg or '为啥' in msg):
        frame = {
            'frame_id': gen_id('frame'),
            'raw_message': user_message,
            'subject': 'run',
            'request': 'explain',
            'freshness': 'current_book',
            'references': {},
            'constraints': {},
            'ambiguity': {'confidence': 0.9, 'notes': []},
        }
        return TurnFrame.model_validate(frame)
    # 第二只为什么 / 第N只
    m = re.search(r'第\s*([一二三四五2-9]|1?\d)\s*只', msg)
    if m and ('为什么' in msg or '为啥' in msg):
        rk = _extract_rank_from_zh(msg)
        if rk is None:
            try:
                rk = int(m.group(1)) if m.group(1).isdigit() else None
            except Exception:
                rk = None
        frame = {
            'frame_id': gen_id('frame'),
            'raw_message': user_message,
            'subject': 'pick',
            'request': 'explain',
            'freshness': 'current_book',
            'references': ({'rank': rk} if rk else {}),
            'constraints': {},
            'ambiguity': {'confidence': 0.85, 'notes': []},
        }
        return TurnFrame.model_validate(frame)
    # 代码 + 卖/止损/止盈/减仓 => exit symbol
    m = re.search(r'(?<!\d)((?:60|00|30)\d{4})(?!\d).*?(卖|止损|止盈|减仓)', msg)
    if m:
        sym = m.group(1)
        frame = {
            'frame_id': gen_id('frame'),
            'raw_message': user_message,
            'subject': 'holding',
            'request': 'exit',
            'freshness': 'latest_5m',
            'references': {'symbol': sym},
            'constraints': {},
            'ambiguity': {'confidence': 0.9, 'notes': []},
        }
        return TurnFrame.model_validate(frame)
    # 现在还能买 / 盘中怎么看
    if ('现在' in msg or '盘中' in msg or '还能' in msg) and ('买' in msg or '怎么看' in msg):
        # best-effort resolve symbol from focus later via _inject_reference_hints
        frame = {
            'frame_id': gen_id('frame'),
            'raw_message': user_message,
            'subject': 'symbol',
            'request': 'live_check',
            'freshness': 'latest_5m',
            'references': {},
            'constraints': {},
            'ambiguity': {'confidence': 0.8, 'notes': []},
        }
        return TurnFrame.model_validate(frame)
    return None


def parse_concern(memory_ctx: Dict[str, Any], book: MarketBook, user_message: str) -> TurnFrame:
    # Fast-path: try deterministic rule parser first
    fr = _quick_rule_parse(memory_ctx, book, user_message)
    if fr is None:
        context = build_context(memory_ctx, book)
        fr = parse_turn_frame(context, user_message)
    fr = _inject_reference_hints(fr, memory_ctx, book)
    fr = normalize_turn_frame(fr)
    return validate_turn_frame(fr)


def normalize_turn_frame(frame: TurnFrame) -> TurnFrame:
    # Ensure technical defaults but do not alter business routing
    frame.references = frame.references or {}
    frame.constraints = frame.constraints or {}
    amb = frame.ambiguity or {}
    try:
        c = float(amb.get('confidence', 0.5))
        amb['confidence'] = max(0.0, min(1.0, c))
    except Exception:
        amb['confidence'] = 0.5
    notes = amb.get('notes')
    amb['notes'] = [str(x) for x in notes] if isinstance(notes, list) else []
    frame.ambiguity = amb
    return frame


def validate_turn_frame(frame: TurnFrame) -> TurnFrame:
    # Pydantic already enforces Literal types; add light guards
    allowed_req = {'chat', 'recommend', 'explain', 'live_check', 'compare', 'exit', 'run_change'}
    allowed_subj = {'run', 'pick', 'symbol', 'compare_set', 'holding', 'market'}
    allowed_fresh = {'current_book', 'latest_5m', 'rebuild_daybook'}
    if frame.request not in allowed_req:
        raise ValueError(f'Illegal request: {frame.request}')
    if frame.subject not in allowed_subj:
        raise ValueError(f'Illegal subject: {frame.subject}')
    if frame.freshness not in allowed_fresh:
        raise ValueError(f'Illegal freshness: {frame.freshness}')
    return frame
