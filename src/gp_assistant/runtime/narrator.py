from __future__ import annotations

from typing import Any, Dict, List

from ..contracts.objects import (
    DecisionBasis,
    CanonicalPick,
    CanonicalRunArtifact,
    EvidencePack,
    GroundingSummary,
    Judgment,
    ReplyBundle,
    TranscriptEvent,
    TurnFrame,
)
from ..core.errors import APIError, LLMPayloadBudgetExceeded
from ..llm.narrate import render_reply
from .context_engine import build_tool_evidence_context
from .dialogue_text import clean_user_reasons, execution_state_label, intraday_runtime_enabled
from .repair import load_repair_status_snapshot


def _freshness_meta(evidence: EvidencePack, run: CanonicalRunArtifact | None = None) -> Dict[str, Any]:
    return {
        "book_version": evidence.book.book_version,
        "artifact_id": (run.artifact_id if run else evidence.book.artifact_id),
        "slot_id": evidence.book.slot_id,
        "slot_status": (run.slot_status if run else evidence.book.slot_status),
        "daybook_effective_day": (
            run.daybook_effective_day if run else evidence.book.daybook_effective_day or evidence.book.daybook.trading_day
        ),
        "pulse_trade_day": (run.pulse_trade_day if run else evidence.book.pulse_trade_day),
        "pulse_slot_at": (run.pulse_slot_at if run else evidence.book.pulse_slot_at),
        "market_phase": (run.market_phase if run else evidence.book.market_phase),
        "data_status": evidence.book.data_status,
    }


def _execution_phrase(pick: CanonicalPick) -> str:
    rec_state = str(getattr(pick, "recommendation_state", "") or "").upper()
    if rec_state == "TRADING_SIGNAL":
        return "current executable trading signal"
    if rec_state == "TRIGGER_PLAN":
        return "waiting for a computed trigger plan"
    if rec_state == "NEXT_SESSION_PLAN":
        return "next trading-window strategy plan"
    if rec_state == "NO_TRADE":
        return "no executable trade plan"
    if rec_state == "UNAVAILABLE":
        return "real data unavailable"
    mapping = {
        "BUY_NOW": "当前可以按计划执行",
        "WAIT_PULLBACK": "逻辑还在，但更适合等回踩确认",
        "WAIT_NEXT_SESSION": "先保留计划，下一交易窗口再确认",
        "WATCH_ONLY": "当前先暂不入场，不建议主动追价",
        "RISK_HIGH": "结构未坏，但位置和环境的风险偏高",
        "INVALIDATED": "已经触发失效条件",
        "UNAVAILABLE": "计划数据暂不完整，只保留暂不入场结论",
    }
    return mapping.get(pick.execution_state, "继续检查")


def _fmt_num(value: Any, digits: int = 2) -> str:
    if value in {None, ""}:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return str(value)


def _fmt_rr(value: Any) -> str:
    try:
        rr = float(value)
    except Exception:
        return "-"
    if rr <= 0.0:
        return "-"
    return f"{rr:.2f}"


ACTION_LABELS = {
    "HOLD": "持有/跟踪",
    "ADD": "开仓/加仓",
    "REDUCE": "减仓",
    "EXIT": "退出",
    "WAIT": "等待",
    "NO_TRADE": "不交易",
}

THESIS_STATE_LABELS = {
    "thesis_strengthened": "thesis 增强",
    "thesis_unchanged": "thesis 未变",
    "thesis_weakening": "thesis 转弱",
    "thesis_invalidated": "thesis 失效",
}


def _decision_line(obj: Any) -> str:
    action = str(getattr(obj, "decision_action", "") or "").upper()
    lifecycle = dict(getattr(obj, "thesis_lifecycle", {}) or {})
    synthesis = dict(getattr(obj, "decision_synthesis", {}) or {})
    if not lifecycle and not synthesis:
        return ""
    state = str(lifecycle.get("current_thesis_state") or synthesis.get("thesis_state") or "").strip()
    rationale = str(synthesis.get("rationale") or "").strip()
    bits: List[str] = []
    if action:
        bits.append(f"决策动作：{ACTION_LABELS.get(action, action)}")
    if state:
        bits.append(f"thesis 状态：{THESIS_STATE_LABELS.get(state, state)}")
    if rationale:
        bits.append(f"依据：{rationale}")
    return "；".join(bits)


def _recommend_fallback_text(run: CanonicalRunArtifact) -> str:
    if not run.picks:
        return "今天不硬给票，当前没有足够清晰的可执行标的。"
    lead = "今天优先跟这几只。" if not run.non_trading else "当前不是连续竞价时段，先给你下一交易窗口计划。"
    lines = [lead]
    for pick in run.picks[:3]:
        lines.append(
            f"第 {pick.rank} 只：{pick.symbol}{f' {pick.name}' if pick.name else ''}，{_execution_phrase(pick)}；"
            f"买入区 {pick.entry_text or '待确认'}，止损 {pick.stop_text or '待确认'}，止盈 {pick.take_text or '待确认'}。"
        )
        decision_line = _decision_line(pick)
        if decision_line:
            lines.append(decision_line)
    if run.run_action == "DEGRADED":
        lines.append("当前环境偏弱，执行上以暂不入场和等待确认为主，不做强推。")
    return "\n".join(lines)


def _no_trade_fallback_text(judgment: Judgment) -> str:
    no_trade = judgment.no_trade
    if no_trade is None:
        return "今天先不硬做，等更清晰的机会。"
    status_reason = str(no_trade.status_reason or "今天先不硬做。").strip()
    lines = [status_reason]
    decision_line = _decision_line(no_trade)
    if decision_line:
        lines.append(decision_line)
    for reason in clean_user_reasons(list(no_trade.no_trade_reasons or [])[:4]):
        if str(reason or "").strip() == status_reason:
            continue
        lines.append(f"- {reason}")
    if no_trade.recovery_conditions:
        lines.append("重新检查这些条件：")
        for condition in list(no_trade.recovery_conditions or [])[:4]:
            lines.append(f"- {condition}")
    return "\n".join(lines)


def _pick_detail_fallback_text(judgment: Judgment) -> str:
    detail = judgment.pick_detail
    if detail is None:
        return judgment.summary
    decision_line = _decision_line(detail)
    decision_text = f"\n{decision_line}" if decision_line else ""
    return (
        f"{detail.symbol}{f' {detail.name}' if detail.name else ''} 的核心逻辑是：{detail.thesis or '当前没有额外补充'}。"
        f"\n入选原因：{detail.why_selected or '当前计划仍然保留。'}"
        f"{decision_text}"
        f"\n买入区：{detail.entry_text or '待确认'}"
        f"\n止损 / 失效：{detail.stop_text or detail.invalidation or '待确认'}"
        f"\n止盈：{detail.take_text or '待确认'}"
        f"\n当前执行状态：{execution_state_label(detail.execution_state)}。"
    )


def _single_stock_fallback_text(judgment: Judgment) -> str:
    analysis = judgment.single_stock_analysis
    if analysis is None:
        return judgment.summary
    status = dict(analysis.data_status or {})
    if status.get("error") == "invalid_symbol":
        return "没有识别到有效的 6 位 A 股代码，暂不做单票分析。"
    if not status.get("ok") and status.get("error"):
        return f"{analysis.symbol} 的日线数据获取失败：{status.get('error')}。"
    summary = dict(analysis.kline_summary or {})
    champion = dict(analysis.champion or {})
    trade_plan = dict(analysis.trade_plan or {})
    diag = dict(trade_plan.get("diagnostics") or {})
    lines = [f"{analysis.symbol}{f' {analysis.name}' if analysis.name else ''} 单票分析：{analysis.overall_state}。"]
    if analysis.last_date:
        lines.append(f"日线截止 {analysis.last_date}，最新收盘 {summary.get('last_close') or '待确认'}。")
    perf_bits: list[str] = []
    for label, key in (("1日", "return_1d_pct"), ("5日", "return_5d_pct"), ("20日", "return_20d_pct")):
        value = summary.get(key)
        if value is not None:
            perf_bits.append(f"{label}{float(value):.2f}%")
    if perf_bits:
        lines.append("近期表现：" + "，".join(perf_bits) + "。")
    if champion:
        lines.append(
            f"冠军策略 {champion.get('strategy') or 'NA'}，评分 {float(champion.get('score') or 0.0):.2f}，"
            f"状态 {champion.get('freshness_state') or 'unknown'}。"
        )
    if diag:
        rr = diag.get("reward_risk")
        rr_text = f"{float(rr):.2f}" if rr is not None else "待确认"
        lines.append(f"执行结构：{diag.get('execution_state') or 'observe_only'}，收益风险比 {rr_text}。")
    if "daily_stale" in analysis.reason_codes:
        lines.append("注意：日线没有补齐到目标交易日，只能作为结构观察，不作为正式交易结论。")
    if "insufficient_history" in analysis.reason_codes:
        lines.append("注意：历史 K 线长度不足，暂不输出冠军评分交易结论。")
    decision_line = _decision_line(analysis)
    if decision_line:
        lines.append(decision_line)
    return "\n".join(lines)


def _live_entry_fallback_text(judgment: Judgment) -> str:
    live_entry = judgment.live_entry
    if live_entry is None:
        return judgment.summary
    metrics: List[str] = []
    if live_entry.vwap is not None:
        metrics.append(f"VWAP {live_entry.vwap:.2f}")
    if live_entry.orb30_high is not None and live_entry.orb30_low is not None:
        metrics.append(f"ORB30 {live_entry.orb30_low:.2f}-{live_entry.orb30_high:.2f}")
    if live_entry.slot_rel_vol is not None:
        metrics.append(f"相对量能 {live_entry.slot_rel_vol:.2f}x")
    if live_entry.entry_distance_pct is not None:
        metrics.append(f"距买点 {live_entry.entry_distance_pct * 100:.2f}%")
    metric_line = "；".join(metrics) if metrics else "当前只保留结构级判断。"
    decision_line = _decision_line(live_entry)
    decision_text = f"\n{decision_line}" if decision_line else ""
    return (
        f"{live_entry.symbol}{f' {live_entry.name}' if live_entry.name else ''} 当前状态："
        f"{execution_state_label(live_entry.execution_state)}。"
        f"\n判断：{live_entry.summary}"
        f"{decision_text}"
        f"\n执行依据：{metric_line}"
        f"\n下一步：{live_entry.next_action}"
    )


def _compare_fallback_text(judgment: Judgment) -> str:
    compare_view = judgment.compare_view
    if compare_view is None:
        return judgment.summary
    lines: List[str] = []
    if compare_view.leader_symbol:
        lines.append(f"当前更优先的是 {compare_view.leader_symbol}。")
    decision_line = _decision_line(compare_view)
    if decision_line:
        lines.append(decision_line)
    for point in compare_view.comparison_points:
        lines.append(f"- {point}")
    for item in compare_view.ranking:
        lines.append(
            f"- {item.get('symbol')}：执行状态 {execution_state_label(str(item.get('execution_state') or ''))}，"
            f"综合分 {float(item.get('final_score') or 0.0):.2f}，风险 {item.get('risk_level')}。"
        )
    return "\n".join(lines) or judgment.summary


def _candidate_compare_fallback_text(judgment: Judgment) -> str:
    view = judgment.candidate_comparison
    if view is None:
        return judgment.summary
    if not view.selected_symbol:
        return f"我按你的约束比较了当前候选，但没有选出足够明确的一只。{view.selection_reason}"
    rank = f"第 {view.selected_rank} 只" if view.selected_rank is not None else "当前候选"
    lines = [
        f"按你的约束，我会选 {rank}：{view.selected_symbol}。",
        f"理由：{view.selection_reason}",
    ]
    decision_line = _decision_line(view)
    if decision_line:
        lines.append(decision_line)
    if view.rejected_symbols:
        lines.append(f"其余候选暂不优先：{'、'.join(view.rejected_symbols)}。")
    lines.append("这个判断使用模型对名称、代码、上下文和你给出的约束的理解；交易执行仍以本地计划和盘中核验为准。")
    return "\n".join(lines)


def _intraday_situation_fallback_text(judgment: Judgment) -> str:
    situation = judgment.intraday_situation
    if situation is None:
        return judgment.summary
    live_entry = situation.live_entry
    source_text = "本地行情已验证" if situation.verified else "盘中价未能验证，只按你提供的数据做条件判断"
    symbol = situation.symbol or "这只票"
    if live_entry is None:
        return f"{symbol}：{source_text}。{situation.summary or judgment.summary}"
    decision_line = _decision_line(situation) or _decision_line(live_entry)
    decision_text = f"{decision_line}\n" if decision_line else ""
    return (
        f"{symbol} 当前判断：{live_entry.summary}\n"
        f"{decision_text}"
        f"数据来源：{source_text}。\n"
        f"下一步：{live_entry.next_action}"
    )


def _exit_fallback_text(judgment: Judgment) -> str:
    exit_view = judgment.exit_decision
    if exit_view is None:
        return judgment.summary
    take = " / ".join(f"{value:.2f}" for value in exit_view.take_profit) if exit_view.take_profit else "待确认"
    stop = f"{exit_view.stop:.2f}" if exit_view.stop is not None else (exit_view.invalidation or "待确认")
    action = str(exit_view.decision_action or exit_view.action or "WAIT").upper()
    decision_line = _decision_line(exit_view)
    decision_text = f"\n{decision_line}" if decision_line else ""
    return (
        f"{exit_view.symbol} 当前建议：{ACTION_LABELS.get(action, action)}。"
        f"{decision_text}"
        f"\n原因：{exit_view.reason}"
        f"\n触发条件：{exit_view.trigger}"
        f"\n风控位：{stop}"
        f"\n止盈位：{take}"
    )


def _run_change_fallback_text(judgment: Judgment) -> str:
    diff = judgment.run_change_view
    if diff is None:
        return judgment.summary
    lines = ["这一轮和上一轮的变化如下："]
    decision_line = _decision_line(diff)
    if decision_line:
        lines.append(f"- {decision_line}")
    if diff.added:
        lines.append(f"- 新增：{'、'.join(diff.added)}")
    if diff.removed:
        lines.append(f"- 移除：{'、'.join(diff.removed)}")
    for change in diff.rank_changes:
        lines.append(f"- {change['symbol']} 排名 {change['from_rank']} -> {change['to_rank']}")
    current = diff.gating_change.get("current", {})
    previous = diff.gating_change.get("previous", {})
    if current or previous:
        lines.append(f"- 当前状态：{current.get('run_action') or '--'} / 上一轮状态：{previous.get('run_action') or '--'}")
    if len(lines) == 1:
        lines.append("- 暂时没有明显的新增、移除或排名变化。")
    return "\n".join(lines)


def _chat_fallback_text() -> str:
    if intraday_runtime_enabled():
        return "可以直接问我今天的机会、某只票现在能不能进、止盈止损怎么设，或者为什么名单变了。"
    return "可以直接问我今天的候选、某只票为什么入选、风控怎么看，或者为什么当前只建议暂不入场。"


def _recommend_fallback_text(run: CanonicalRunArtifact) -> str:
    mode = str(run.recommendation_state or run.run_action or "NO_TRADE")
    phase = run.market_phase or "unknown"
    executable = any(pick.can_execute_now for pick in run.picks)
    header = [
        f"当前模式：{mode}",
        f"当前时段：{phase}",
        f"数据来源：artifact_id={run.artifact_id or '-'} / slot_id={run.slot_id or '-'} / as_of={run.as_of}",
        f"是否可立即执行：{'是' if executable else '否'}",
    ]
    if not run.picks:
        reasons = "；".join(list(run.no_trade_reasons or [])[:4]) or run.status_reason or "没有可用计划"
        return "\n".join([*header, f"结论：{mode}，{reasons}"])
    lines = list(header)
    for pick in run.picks[:3]:
        plan = dict(pick.execution_plan or {})
        ctx = dict(pick.explain_context or {})
        risks = dict(pick.risk_pack or {})
        lines.append(f"\n{pick.rank}. {pick.symbol}{(' ' + pick.name) if pick.name else ''}")
        lines.append(f"结论：{pick.recommendation_state}，{_execution_phrase(pick)}。")
        lines.append(f"策略：{pick.champion_strategy or 'NA'}，分数 {pick.champion_strategy_score:.2f}。")
        lines.append(
            "计划："
            f"trigger={_fmt_num(plan.get('trigger_price') or ctx.get('trigger_price'))}，"
            f"entry={_fmt_num(plan.get('entry_low') or ctx.get('entry_low'))}-{_fmt_num(plan.get('entry_high') or ctx.get('entry_high'))}，"
            f"stop={_fmt_num(plan.get('stop_price') or ctx.get('stop_price'))}，"
            f"take={_fmt_num(plan.get('take1') or ctx.get('take1'))} / {_fmt_num(plan.get('take2') or ctx.get('take2'))}，"
            f"RR={_fmt_rr(plan.get('rr_to_take1') or ctx.get('rr_to_take1'))}。"
        )
        reasons = list(pick.strategy_reason_codes or ctx.get("strategy_reason_codes") or [])[:4]
        if reasons:
            lines.append("关键证据：" + "，".join(str(item) for item in reasons))
        risk_bits = list(risks.get("main_risks") or ctx.get("main_risks") or [])[:4]
        if risk_bits:
            lines.append("风险：" + "，".join(str(item) for item in risk_bits))
        decision_line = _decision_line(pick)
        if decision_line:
            lines.append(decision_line)
        next_wait = plan.get("confirmation_conditions") or ctx.get("what_would_improve") or []
        if next_wait:
            lines.append("下一步：" + "，".join(str(item) for item in list(next_wait)[:3]))
    return "\n".join(lines)


def _fallback_text(judgment: Judgment) -> str:
    if judgment.kind == "recommend" and judgment.canonical_run is not None:
        return _recommend_fallback_text(judgment.canonical_run)
    if judgment.kind == "no_trade":
        return _no_trade_fallback_text(judgment)
    if judgment.kind == "pick_detail":
        return _pick_detail_fallback_text(judgment)
    if judgment.kind == "single_stock_query":
        return _single_stock_fallback_text(judgment)
    if judgment.kind == "live_entry_check":
        return _live_entry_fallback_text(judgment)
    if judgment.kind == "compare":
        return _compare_fallback_text(judgment)
    if judgment.kind == "candidate_compare":
        return _candidate_compare_fallback_text(judgment)
    if judgment.kind == "intraday_situation":
        return _intraday_situation_fallback_text(judgment)
    if judgment.kind == "exit_decision":
        return _exit_fallback_text(judgment)
    if judgment.kind == "run_change":
        return _run_change_fallback_text(judgment)
    return _chat_fallback_text()


def build_default_text(judgment: Judgment) -> str:
    return _fallback_text(judgment)


def _text_has_min_signal(text: str, judgment: Judgment) -> bool:
    body = str(text or "").strip()
    if len(body) < 24:
        return False
    if judgment.kind in {"recommend", "pick_detail", "single_stock_query", "live_entry_check"} and len(body) < 40:
        return False
    if judgment.kind in {"recommend", "pick_detail", "single_stock_query", "live_entry_check"} and "\n" not in body:
        return False
    return True


def _message_for_recommend(judgment: Judgment, text: str) -> Dict[str, Any]:
    run = judgment.canonical_run
    assert run is not None
    top_symbol = run.picks[0].symbol if run.picks else None
    intraday_enabled = intraday_runtime_enabled()
    execution_note = "盘中执行计划"
    if not intraday_enabled:
        execution_note = "当前只保留日线计划与暂不入场结论"
    elif run.non_trading:
        execution_note = "下一交易窗口计划"
    return {
        "message_kind": "recommend",
        "lead_summary": run.status_reason,
        "decision_state": run.recommendation_state,
        "recommendation_state": run.recommendation_state,
        "market_summary": run.status_reason,
        "execution_note": execution_note,
        "risk_note": ("当前环境偏弱，执行上以确认优先。" if run.run_action == "DEGRADED" else None),
        "narrative_text": text,
        "picks": [pick.model_dump() for pick in run.picks],
        "run": run.model_dump(),
        "explain_context": run.explain_context,
        "decision_evidence_pack": run.decision_evidence_pack,
        "followup_suggestions": [
            (f"为什么推荐第 {run.picks[0].rank} 只" if run.picks else "为什么今天先暂不入场"),
            (f"{top_symbol} 现在还能买吗" if top_symbol else "重新转强要看什么"),
            (f"{top_symbol} 的止盈止损点" if top_symbol else "明天开盘前看什么"),
            ("第一只和第二只比呢" if len(run.picks) >= 2 else "为什么这次和上次不一样"),
        ],
    }


def _decision_payload(judgment: Judgment) -> Dict[str, Any]:
    return {
        "decision_context_model": dict(judgment.decision_context_model or {}),
        "thesis_lifecycle": dict(judgment.thesis_lifecycle or {}),
        "decision_action": str(judgment.decision_action or "WAIT"),
        "decision_synthesis": dict(judgment.decision_synthesis or {}),
    }


def _build_canonical_message(evidence: EvidencePack, judgment: Judgment, text: str) -> Dict[str, Any]:
    def attach(message: Dict[str, Any]) -> Dict[str, Any]:
        message.update(_decision_payload(judgment))
        return message

    if judgment.kind == "recommend" and judgment.canonical_run is not None:
        message = _message_for_recommend(judgment, text)
        message["freshness_meta"] = _freshness_meta(evidence, judgment.canonical_run)
        return attach(message)
    if judgment.kind == "no_trade":
        run = judgment.canonical_run
        no_trade = judgment.no_trade
        return attach({
            "message_kind": "no_trade",
            "narrative_text": text,
            "run": (run.model_dump() if run else None),
            "market_summary": (no_trade.market_summary if no_trade else judgment.summary),
            "reason": (no_trade.status_reason if no_trade else judgment.summary),
            "no_trade_reasons": (no_trade.no_trade_reasons if no_trade else []),
            "recovery_conditions": (no_trade.recovery_conditions if no_trade else []),
            "followup_suggestions": ["今天给我 3 只", "为什么先暂不入场", "重新转强要看什么"],
            "freshness_meta": _freshness_meta(evidence, run),
        })
    if judgment.kind == "pick_detail":
        run = judgment.canonical_run
        detail = judgment.pick_detail
        symbol = detail.symbol if detail else None
        return attach({
            "message_kind": "pick_detail",
            "narrative_text": text,
            "pick": (detail.model_dump() if detail else {}),
            "run": (run.model_dump() if run else None),
            "symbol": symbol,
            "followup_suggestions": ["这只现在还能买吗", "和第一只比呢", "风控怎么设"],
            "freshness_meta": _freshness_meta(evidence, run),
        })
    if judgment.kind == "single_stock_query":
        analysis = judgment.single_stock_analysis
        symbol = analysis.symbol if analysis else None
        return attach({
            "message_kind": "single_stock_query",
            "narrative_text": text,
            "analysis": (analysis.model_dump() if analysis else {}),
            "symbol": symbol,
            "followup_suggestions": [
                f"{symbol} 的风险点" if symbol else "这只的风险点",
                f"{symbol} 和当前第一只比" if symbol else "和当前第一只比",
                f"{symbol} 该不该卖" if symbol else "这只该不该卖",
            ],
            "freshness_meta": _freshness_meta(evidence, judgment.canonical_run),
        })
    if judgment.kind == "live_entry_check":
        run = judgment.canonical_run
        live_entry = judgment.live_entry
        symbol = live_entry.symbol if live_entry else None
        return attach({
            "message_kind": "live_entry_check",
            "narrative_text": text,
            "live_check": (live_entry.model_dump() if live_entry else {}),
            "run": (run.model_dump() if run else None),
            "symbol": symbol,
            "followup_suggestions": ["要不要等回踩", "这只止盈止损怎么设", "为什么当前暂不入场"],
            "freshness_meta": _freshness_meta(evidence, run),
        })
    if judgment.kind == "compare":
        run = judgment.canonical_run
        return attach({
            "message_kind": "compare",
            "narrative_text": text,
            "compare": (judgment.compare_view.model_dump() if judgment.compare_view else {}),
            "run": (run.model_dump() if run else None),
            "symbols": ([entry.symbol for entry in judgment.compare_entries] if judgment.compare_entries else []),
            "followup_suggestions": ["为什么第二个不是第一", "第二只差在哪", "这只现在还能买吗"],
            "freshness_meta": _freshness_meta(evidence, run),
        })
    if judgment.kind == "candidate_compare":
        run = judgment.canonical_run
        view = judgment.candidate_comparison
        return attach({
            "message_kind": "candidate_compare",
            "narrative_text": text,
            "candidate_compare": (view.model_dump() if view else {}),
            "compare": {
                "compared_symbols": (view.compared_symbols if view else []),
                "leader_symbol": (view.selected_symbol if view else None),
                "ranking": [
                    {"symbol": symbol, "selected": bool(view and symbol == view.selected_symbol)}
                    for symbol in (view.candidate_scope if view else [])
                ],
                "comparison_points": ([view.selection_reason] if view and view.selection_reason else []),
                "source_run_id": (view.source_run_id if view else None),
                "data_provenance": {"source": "model_selection_with_program_scope_check"},
            },
            "run": (run.model_dump() if run else None),
            "symbols": (view.compared_symbols if view else []),
            "followup_suggestions": ["这只现在还能买吗", "和第一只比呢", "按盘中情况再看一下"],
            "freshness_meta": _freshness_meta(evidence, run),
        })
    if judgment.kind == "intraday_situation":
        run = judgment.canonical_run
        situation = judgment.intraday_situation
        symbol = situation.symbol if situation else None
        return attach({
            "message_kind": "intraday_situation",
            "narrative_text": text,
            "intraday_situation": (situation.model_dump() if situation else {}),
            "live_check": (situation.live_entry.model_dump() if situation and situation.live_entry else {}),
            "run": (run.model_dump() if run else None),
            "symbol": symbol,
            "followup_suggestions": ["要不要等回踩", "如果再冲高怎么办", "止损放哪里"],
            "freshness_meta": _freshness_meta(evidence, run),
        })
    if judgment.kind == "exit_decision":
        run = judgment.canonical_run
        exit_view = judgment.exit_decision
        symbol = exit_view.symbol if exit_view else None
        return attach({
            "message_kind": "exit_decision",
            "narrative_text": text,
            "exit_decision": (exit_view.model_dump() if exit_view else {}),
            "run": (run.model_dump() if run else None),
            "symbol": symbol,
            "followup_suggestions": ["这只逻辑还在吗", "现在还能买吗", "为什么这次和上次不一样"],
            "freshness_meta": _freshness_meta(evidence, run),
        })
    if judgment.kind == "run_change":
        return attach({
            "message_kind": "run_change",
            "narrative_text": text,
            "run_change": (judgment.run_change_view.model_dump() if judgment.run_change_view else {}),
            "followup_suggestions": ["之前那只为什么没了", "今天给我 3 只", "第一只和第二只比呢"],
            "freshness_meta": _freshness_meta(evidence, judgment.canonical_run),
        })
    return attach({
        "message_kind": "chat",
        "narrative_text": text,
        "followup_suggestions": ["今天给我 3 只", "第二个现在还能看吗", "600519 现在该不该卖"],
        "freshness_meta": _freshness_meta(evidence, judgment.canonical_run),
    })


def _message_payload(frame: TurnFrame, evidence: EvidencePack, judgment: Judgment, recent_turns: List[TranscriptEvent] | None) -> Dict[str, Any]:
    return {
        "tool_evidence_context": build_tool_evidence_context(
            frame,
            evidence,
            judgment,
            recent_turns,
        )
    }


def _repair_state() -> tuple[str, str | None]:
    snapshot = load_repair_status_snapshot()
    if snapshot is None:
        return "ready", None
    status = str(snapshot.repair_status or "ready").strip().lower()
    if status in {"running", "blocked", "failed", "ready"}:
        return status, snapshot.repair_stage
    if status == "idle":
        return "ready", None
    return "ready", snapshot.repair_stage


def _decision_basis(evidence: EvidencePack, judgment: Judgment) -> DecisionBasis:
    run = judgment.canonical_run
    labels: List[str] = []
    risk_notes: List[str] = []
    selection_reason = judgment.summary
    execution_reason = None
    if judgment.decision_synthesis:
        labels.extend(["决策模型", "thesis生命周期"])
        synthesis = dict(judgment.decision_synthesis or {})
        if synthesis.get("rationale"):
            execution_reason = str(synthesis.get("rationale"))
    if run is not None:
        labels.append("日线计划")
        if run.pulse_slot_at and intraday_runtime_enabled():
            labels.append("盘中执行")
        if run.no_trade_reasons:
            labels.append("风险约束")
            risk_notes.extend(clean_user_reasons(run.no_trade_reasons[:4]))
        if run.picks:
            top = run.picks[0]
            labels.append("入选逻辑")
            selection_reason = top.why_selected or top.thesis or run.status_reason or judgment.summary
            execution_reason = top.entry_text or top.stop_text or top.take_text
    elif judgment.pick_detail is not None:
        labels.extend(["单票逻辑", "执行计划"])
        selection_reason = judgment.pick_detail.why_selected or judgment.pick_detail.thesis or judgment.summary
        execution_reason = judgment.pick_detail.entry_text or judgment.pick_detail.stop_text or judgment.pick_detail.take_text
    elif judgment.single_stock_analysis is not None:
        labels.extend(["single_stock_daily", "champion_strategy"])
        analysis = judgment.single_stock_analysis
        selection_reason = analysis.overall_state or judgment.summary
        diag = dict((analysis.trade_plan or {}).get("diagnostics") or {})
        execution_reason = str(diag.get("execution_state") or analysis.overall_state)
        risk_notes.extend(list(analysis.reason_codes or []))
    elif judgment.live_entry is not None:
        labels.extend(["执行判断", "风险边界"])
        selection_reason = judgment.live_entry.summary or judgment.summary
        execution_reason = judgment.live_entry.next_action
    elif judgment.compare_view is not None:
        labels.extend(["相对强弱", "执行优先级"])
        selection_reason = judgment.summary
    elif judgment.candidate_comparison is not None:
        labels.extend(["模型候选选择", "候选范围校验"])
        selection_reason = judgment.candidate_comparison.selection_reason or judgment.summary
    elif judgment.intraday_situation is not None:
        labels.extend(["盘中用户输入", "执行判断"])
        selection_reason = judgment.intraday_situation.summary or judgment.summary
        if not judgment.intraday_situation.verified:
            risk_notes.append("盘中价未能验证，只能按用户提供的数据条件判断")
    elif judgment.exit_decision is not None:
        labels.extend(["持仓风控", "止盈止损"])
        selection_reason = judgment.exit_decision.reason or judgment.summary
        execution_reason = judgment.exit_decision.trigger
    if not labels:
        labels.append("对话上下文")
    repair_status, repair_stage = _repair_state()
    return DecisionBasis(
        labels=list(dict.fromkeys(labels)),
        market_phase=evidence.book.market_phase,
        daily_target_day=evidence.book.daybook_effective_day or evidence.book.daybook.trading_day,
        pulse_slot_at=evidence.book.pulse_slot_at,
        selection_reason=selection_reason,
        execution_reason=execution_reason,
        risk_notes=list(dict.fromkeys([item for item in risk_notes if str(item).strip()])),
        repair_status=repair_status,
        repair_stage=repair_stage,
    )


def _grounding_summary(evidence: EvidencePack, judgment: Judgment) -> GroundingSummary:
    basis = _decision_basis(evidence, judgment)
    return GroundingSummary(
        market_phase=basis.market_phase,
        daily_target_day=basis.daily_target_day,
        pulse_slot_at=basis.pulse_slot_at,
        repair_status=basis.repair_status,
        decision_basis_labels=basis.labels,
    )


def build_structured_reply(
    session_id: str,
    evidence: EvidencePack,
    judgment: Judgment,
    *,
    text: str,
) -> ReplyBundle:
    run = judgment.canonical_run
    message = _build_canonical_message(evidence, judgment, text)
    symbols: List[str] = []
    if judgment.candidate_comparison is not None:
        symbols = [symbol for symbol in judgment.candidate_comparison.compared_symbols if symbol]
    elif judgment.intraday_situation is not None and judgment.intraday_situation.symbol:
        symbols = [judgment.intraday_situation.symbol]
    elif judgment.single_stock_analysis is not None and judgment.single_stock_analysis.symbol:
        symbols = [judgment.single_stock_analysis.symbol]
    elif judgment.subject_entry is not None:
        symbols = [judgment.subject_entry.symbol]
    elif judgment.compare_entries:
        symbols = [entry.symbol for entry in judgment.compare_entries]
    elif run is not None:
        symbols = [pick.symbol for pick in run.picks]

    snapshot = run.model_dump() if run is not None else None
    right_panel = {
        "snapshot": snapshot,
        "trading_day": evidence.book.trading_day,
        "artifact_id": (run.artifact_id if run else evidence.book.artifact_id),
        "slot_id": evidence.book.slot_id,
        "slot_status": (run.slot_status if run else evidence.book.slot_status),
        "last_closed_5m": evidence.book.last_closed_5m,
        "tradeable": (run.tradeable if run else evidence.book.daybook.tradeable),
        "run_action": (run.run_action if run else None),
        "recommendation_state": (run.recommendation_state if run else None),
        "top3": ([pick.model_dump() for pick in run.picks[:3]] if run else []),
        "decision_evidence_pack": (run.decision_evidence_pack if run else {}),
        "decision_context_model": dict(judgment.decision_context_model or {}),
        "thesis_lifecycle": dict(judgment.thesis_lifecycle or {}),
        "decision_action": str(judgment.decision_action or "WAIT"),
        "decision_synthesis": dict(judgment.decision_synthesis or {}),
    }
    serenity_fact_ids: List[str] = []
    if run is not None:
        for pick in run.picks:
            if symbols and pick.symbol not in set(symbols):
                continue
            serenity = dict((pick.explain_context or {}).get("serenity") or {})
            serenity_fact_ids.extend(str(item) for item in (serenity.get("fact_ids") or []) if str(item))
    return ReplyBundle(
        session_id=session_id,
        text=text,
        kind=judgment.kind,
        run_id=(run.run_id if run else (judgment.run.run_id if judgment.run else None)),
        symbols=symbols,
        right_panel=right_panel,
        ui_items=[],
        message=message,
        evidence_refs=list(dict.fromkeys([*list(judgment.evidence_refs or []), *serenity_fact_ids])),
        grounding_summary=_grounding_summary(evidence, judgment).model_dump(),
        decision_basis=_decision_basis(evidence, judgment).model_dump(),
        tool_trace={},
        agent_trace={},
    )


def build_reply(
    session_id: str,
    frame: TurnFrame,
    evidence: EvidencePack,
    judgment: Judgment,
    *,
    recent_turns: List[TranscriptEvent] | None = None,
) -> ReplyBundle:
    fallback_text = _fallback_text(judgment)
    try:
        text = render_reply(_message_payload(frame, evidence, judgment, recent_turns))
    except LLMPayloadBudgetExceeded:
        raise
    except (APIError, RuntimeError):
        text = fallback_text

    if not text or not _text_has_min_signal(text, judgment):
        text = fallback_text

    reply = build_structured_reply(session_id, evidence, judgment, text=text)
    reply.tool_trace = {"frame": frame.model_dump()}
    return reply
