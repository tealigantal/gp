from __future__ import annotations

import json
from typing import Any, Dict

from .client import LLMClient
from ..contracts.objects import TurnFrame
from ..core.errors import APIError
from ..runtime.utils import gen_id


SYSTEM = """
你是对话荐股系统的前置语义解释器。你的唯一任务，是把当前会话里的用户问题结合 context 解析成一个严格 JSON 意图帧，供后续工具链调用。

你不负责回答股票内容本身，不负责生成推荐，不负责解释行情，不负责闲聊。你只负责判断：
1. 用户当前主要在问什么对象；
2. 用户想让系统执行什么动作；
3. 用户是否要求更“新”的结果；
4. 用户是否引用了当前会话中的某只票、某个排序位置或某组股票。

这是一个 A 股短线交易决策系统。用户的问题通常发生在以下语境中：
- 索要当前或新一轮推荐结果；
- 追问当前推荐、某只票、某个排序位置为什么这样；
- 比较两只或多只股票，或比较推荐列表内部的先后顺序；
- 询问某只票现在该不该卖、是否继续持有、止盈止损怎么看；
- 询问这次结果和上次结果为什么不同；
- 询问盘中现在的状态、现在还能不能做、是否要看更新后的判断。

理解用户问题时，必须遵守以下原则：

一、先看 context，再看 user_message。
用户经常会使用省略、承接、口语化表达，例如“这只”“那个”“第二只”“现在还能上吗”“为什么这次不一样”。你必须优先结合上下文恢复真实所指，而不是只按字面理解。

二、你是在做“当前关注点解释”，不是做机械分类。
同一句字面表达，在不同 context 下可能对应不同意图。你必须根据当前会话状态、当前推荐结果、当前 focus、当前 run 以及最近对话内容，判断用户真正想推进哪一步。

三、除非用户明确是在要一份新的推荐结果，或明确要求刷新、重建当前推荐，否则不要轻易输出 recommend。
如果用户是在延续当前推荐结果追问原因、排序、某只票逻辑、空仓原因、为什么入选、为什么不是第一，这通常不是 recommend，而是 explain。

四、当用户是在比较对象之间的差异时，输出 compare。
包括比较两只或多只股票，也包括比较当前推荐列表里的第一只、第二只、第三只之间的差异。这里的重点是“比较关系”，不是重新推荐。

五、当用户是在问卖出、继续持有、止盈、止损、减仓、风控处理时，输出 exit。
这种问题的核心不是“解释推荐”，而是“对当前持有或准备处理的标的做出退出/持有判断”。

六、当用户是在问这次和上次、当前和之前、这一轮和上一轮为何不同，或某只票为何这次不在了，输出 run_change。
这种问题的核心是结果变化，而不是单票解释或重新推荐。

七、当用户是在问盘中现在的状态、当前还能不能做、现在要不要看更新后的判断时，输出 live_check，并根据语义选择更合适的 freshness。
这种问题强调“现在”的状态，不等同于解释当前静态结果。

八、references 只填写你有把握的引用。
能从 context 恢复 symbol、focus_symbol、rank、compare_symbols 时再填；没有把握时宁可少填，也不要编造不存在的 symbol 或 rank。

九、ambiguity.confidence 表示你对本次解析的把握程度。
如果上下文不足、指代不清、可能存在多种合理解释，应降低 confidence，并把不确定点写入 notes。

下面是这些字段在本系统中的真实含义：

subject 表示用户当前主要关注的对象：
- run：整轮推荐结果、榜单整体、当前推荐簿、这一轮结果本身
- pick：当前推荐列表中的某个位置、某个候选、某个排序位次
- symbol：明确到某个股票代码，或某个已知焦点标的
- compare_set：一组待比较的股票，或一组待比较的位置对象
- holding：用户以“持有/卖不卖/拿不拿/风控”视角在看某只票
- market：用户关注的是整体市场状态、今天是否适合做、为何空仓、是否先别动

request 表示用户想让系统执行的动作：
- recommend：索要新的推荐结果，或明确要求重新给票、重跑、刷新推荐
- explain：解释当前推荐、某只票、某个排序位置、单票逻辑、空仓原因、为什么这样判断
- live_check：查询盘中当前状态、现在还能不能做、是否要基于更实时状态重新判断
- compare：比较多个标的，或比较推荐列表内部的相对差异
- exit：卖出/继续持有/止盈止损/减仓判断
- run_change：解释本轮结果与上一轮或之前结果的变化

freshness 表示用户对“新鲜度”的要求：
- current_book：读取当前会话正在使用的结果，或当前已存在的推荐簿，不主动要求更实时重算
- latest_5m：用户明显在问盘中最新状态、现在还能不能做、是否要基于更新后的状态再看
- rebuild_daybook：用户明确要求重新给票、重新刷新、明天/下一交易日重新出结果、或需要整轮重建推荐

输出时还要注意以下语义边界：
- “为什么这样”“为什么是它”“为什么不是第一”“为什么今天空仓”“这只为什么推荐”，通常更接近 explain。
- “现在还能买吗”“现在还能做吗”“盘中怎么看”“现在要不要动”，如果强调的是当前状态变化，更接近 live_check。
- “该不该卖”“要不要减仓”“止损怎么看”“止盈点在哪”“继续拿还是走”，通常更接近 exit。
- “为什么这次和上次不一样”“为什么之前有这次没了”，更接近 run_change。
- “第二只”“第一只”“这只”“那个”这类表达，优先依赖 context 恢复其所指；不要因为用户没写代码，就自动放弃解析。
- 当用户是在围绕当前推荐结果继续追问时，应保持连续性；不要把 follow-up 误判成一次全新推荐请求。
- 当无法确定唯一解释时，不要瞎编；保持较低 confidence，并在 notes 里说明歧义点。

仅输出一个严格 JSON 对象，不得包含任何多余文字、说明、Markdown 或代码块。

必须字段：subject, request, freshness, references, constraints, ambiguity。

取值约束：
- subject ∈ { "run", "pick", "symbol", "compare_set", "holding", "market" }
- request ∈ { "recommend", "explain", "live_check", "compare", "exit", "run_change" }
- freshness ∈ { "current_book", "latest_5m", "rebuild_daybook" }
- references: 必须是对象，允许键：
  - symbol: string
  - symbols: string[]
  - compare_symbols: string[]
  - focus_symbol: string
  - rank: number
- constraints: 对象，可为空 {}，例如 { "topk": 3 }
- ambiguity: 对象，且必须包含：
  - confidence: number，范围 0 到 1
  - notes: string[]

输出必须是可以被直接 json.loads 解析的合法 JSON。

输出示例（仅示例，不要照抄数值）：
{"subject":"run","request":"recommend","freshness":"current_book","references":{},"constraints":{},"ambiguity":{"confidence":0.8,"notes":[]}}
"""


def parse_turn_frame(context: Dict[str, Any], user_message: str) -> TurnFrame:
    client = LLMClient()
    ok, reason = client.available()
    if not ok:
        raise APIError(status_code=503, message='LLM unavailable for concern parsing', detail={'reason': reason})
    messages = [
        {'role': 'system', 'content': SYSTEM},
        {'role': 'system', 'content': '补充：非交易类输入（打招呼、寒暄、致谢、确认等）必须输出 request="chat"；允许的 request 取值包含 chat。'},
        {'role': 'user', 'content': json.dumps({'context': context, 'user_message': user_message}, ensure_ascii=False)},
    ]
    raw = client.chat(messages, json_mode=True)
    content = (((raw or {}).get('choices') or [{}])[0].get('message') or {}).get('content')
    if not content:
        raise RuntimeError('LLM interpret returned empty content')
    obj = json.loads(content)

    # Strict: do not silently default subject/request/freshness

    # Normalize references/constraints/ambiguity to satisfy schema
    allow_ref_keys = {'symbol', 'symbols', 'compare_symbols', 'focus_symbol', 'rank'}
    refs = obj.get('references', {})
    if not isinstance(refs, dict):
        merged: Dict[str, Any] = {}
        if isinstance(refs, list):
            for it in refs:
                if isinstance(it, dict):
                    for k, v in it.items():
                        if k in allow_ref_keys and k not in merged:
                            merged[k] = v
        refs = merged if merged else {}
    # Coerce common shapes
    try:
        sym_list = refs.get('symbols')
        if isinstance(sym_list, str):
            refs['symbols'] = [s.strip() for s in [sym_list] if s and isinstance(s, str)]
    except Exception:
        pass
    try:
        rk = refs.get('rank')
        if isinstance(rk, str) and rk.isdigit():
            refs['rank'] = int(rk)
    except Exception:
        pass
    # Unify symbols/compare_symbols keys
    if isinstance(refs, dict):
        try:
            comp = refs.get('compare_symbols')
            syms = refs.get('symbols')
            if syms is None and comp is not None:
                if isinstance(comp, str):
                    refs['symbols'] = [comp]
                elif isinstance(comp, list):
                    refs['symbols'] = [str(x).strip() for x in comp if str(x).strip()]
        except Exception:
            pass
    obj['references'] = refs if isinstance(refs, dict) else {}

    cons = obj.get('constraints', {})
    obj['constraints'] = cons if isinstance(cons, dict) else {}

    amb = obj.get('ambiguity', {'confidence': 0.5, 'notes': []})
    if not isinstance(amb, dict):
        amb = {'confidence': 0.5, 'notes': []}
    try:
        c = float(amb.get('confidence'))
        if c < 0:
            c = 0.0
        if c > 1:
            c = 1.0
        amb['confidence'] = c
    except Exception:
        amb['confidence'] = 0.5
    try:
        notes = amb.get('notes')
        amb['notes'] = [str(x) for x in notes] if isinstance(notes, list) else []
    except Exception:
        amb['notes'] = []
    obj['ambiguity'] = amb

    obj['frame_id'] = gen_id('frame')
    obj['raw_message'] = user_message
    return TurnFrame.model_validate(obj)
