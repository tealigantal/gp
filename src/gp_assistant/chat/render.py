from __future__ import annotations

from typing import Any, Dict, List

from ..llm.client import LLMClient


def _render_pick(it: Dict[str, Any]) -> str:
    sym = it.get("symbol")
    theme = it.get("theme") or (it.get("source_reason") or "主线回踩")
    score = it.get("score", 0)
    q = it.get("q_grade", it.get("indicators", {}).get("q_grade", it.get("q", "Q1")))
    chip = it.get("chip", {})
    ann = it.get("announcement_risk", {})
    ev = it.get("event_risk", {})
    bands = {
        "S1": round(float(chip.get("band_90_low", 0.0)), 2),
        "S2": round(float(chip.get("avg_cost", 0.0)), 2),
        "R1": round(float(chip.get("band_90_high", 0.0)), 2),
        "R2": round(float(chip.get("band_90_high", 0.0)) * 1.02, 2),
    }
    lines: List[str] = []
    lines.append(f"标的 {sym}｜主题：{theme}｜评分：{score:.1f}")
    lines.append(
        f"- 指标面板：ATR%={it.get('atr_pct', it.get('indicators',{}).get('atr_pct',0)):.2%}，"
        f"Gap={it.get('gap_pct', it.get('indicators',{}).get('gap_pct',0)):.2%}，"
        f"Slope20={it.get('indicators',{}).get('slope20',0):.2%}"
    )
    lines.append(f"- 噪声等级Q：{q}（Q2以上A窗禁买，B窗收盘确认）")
    lines.append(
        f"- 筹码/成本带：S1≈{bands['S1']}｜S2≈{bands['S2']}｜R1≈{bands['R1']}｜R2≈{bands['R2']}"
        f"（模型{chip.get('model_used','?')}，置信度{chip.get('confidence','low')}）"
    )
    lines.append(
        f"- 形态统计：5日胜率≈{it.get('stats',{}).get('win_rate_5',0):.0%}，"
        f"样本k={it.get('stats',{}).get('k',0)}（不足则降权）"
    )
    lines.append(
        f"- 公告与事件：公告风险={ann.get('risk_level','low')}；事件={ev.get('event_risk','low')}"
    )
    # Champion strategy snapshot (if present)
    champ = it.get("champion") or {}
    tp = it.get("trade_plan") or {}
    if champ and tp:
        cb = tp.get("bands", {}) or {}
        try:
            s1 = round(float(cb.get("S1", bands["S1"])), 2)
            s2 = round(float(cb.get("S2", bands["S2"])), 2)
            r1 = round(float(cb.get("R1", bands["R1"])), 2)
            r2 = round(float(cb.get("R2", bands["R2"])), 2)
        except Exception:
            s1, s2, r1, r2 = bands["S1"], bands["S2"], bands["R1"], bands["R2"]
        lines.append(
            f"- 冠军策略：{champ.get('strategy','NA')}｜关键带 S1≈{s1} / S2≈{s2} / R1≈{r1} / R2≈{r2}"
        )
    # Two-window action
    lines.append(
        "- A窗动作：关键带回收→承接一项成立（低点不破/量能衰减/分时回收/横向消化），否则观望"
    )
    lines.append(
        "- B窗动作：收盘前结构确认（站稳关键结构且不大幅回落），不满足放弃；不追价"
    )
    lines.append(
        "- 风险：仓位100/200股观察；止损：收盘有效跌破支撑带；时间止损：2-3日不强必走；禁止摊平亏损"
    )
    lines.append(
        "- 失效条件：放量不涨/频繁冲高回落/上影线明显/贴近压力位，触发一票否决则放弃"
    )
    return "\n".join(lines)


def render_recommendation(obj: Dict[str, Any]) -> str:
    env = obj.get("env", {})
    themes = obj.get("themes", [])
    picks = obj.get("picks", [])
    # First paragraph: environment -> themes -> candidates summary
    head: List[str] = []
    head.append(
        f"环境分层：{env.get('grade','C')}（依据：" + "；".join(env.get("reasons", [])) + "）"
    )
    if env.get("grade") == "D":
        # 只有在不可交易时才给“空仓倾向”的强结论；可交易则给“防守/轻仓”提示
        if not bool(obj.get("tradeable")):
            head.append("结论：空仓倾向；恢复条件：" + "；".join(env.get("recovery_conditions", [])))
        else:
            head.append("建议防守：轻仓/观察为主；恢复条件：" + "；".join(env.get("recovery_conditions", [])))
    if themes:
        th = [f"{t.get('name')}({t.get('strength')})" for t in themes[:2]]
        head.append("主线主题：" + "；".join(th))
    head_txt = "\n".join(head)
    # Second paragraph
    body_lines: List[str] = []
    for it in picks:
        body_lines.append(_render_pick(it))
    body = "\n\n".join(body_lines) if body_lines else "（无可执行标的）"
    checklist = "\n".join(obj.get("execution_checklist", [])[:5])
    return f"【市场环境与主题】\n{head_txt}\n\n【冠军策略与交易计划】\n{body}\n\n今日执行清单：\n{checklist}"


def render_recommendation_narrative(obj: Dict[str, Any]) -> str:
    """LLM 只做“改写”，不新增事实；降级或未配置直接走可验证文本。

    - 若 debug 显示降级（如 SNAPSHOT_MISSING）或 LLM 未配置，则返回结构化文本；
    - 正常情况下，先生成结构化文本，再交给 LLM 做“仅限改写/润色”。
    """
    picks = obj.get("picks", [])
    debug = obj.get("debug", {}) or {}
    degraded = bool(debug.get("degraded")) or bool((debug.get("snapshot") or {}).get("missing"))

    base_text = render_recommendation(obj)

    client = LLMClient()
    ok, reason = client.available()
    if degraded or not ok:
        # 降级或 LLM 不可用：直接返回可验证的结构化文本
        return base_text if ok or not reason else f"[narrative_unavailable] {reason}\n\n" + base_text

    sys_prompt = (
        "你是内部投研搭档。对用户提供的‘基础文本’仅进行改写润色，必须遵守：\n"
        "- 严禁新增任何事实、日期、价格、‘今天/昨日/开盘/收盘/阳线/阴线’等时序表述；\n"
        "- 不得改写数值含义，所有指标/百分比只能沿用原文；\n"
        "- 不添加免责声明，不扩写法律合规模块；\n"
        "- 语言口语化、紧凑，200字以内；\n"
        "- 如果基础文本为空或无标的，原样简短报‘暂无可执行标的’。\n"
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": base_text},
    ]

    def _looks_like_refusal(txt: str) -> bool:
        import re
        return bool(re.search(r"(无法提供|不构成|仅供参考|建议.*咨询)", txt))

    try:
        resp = client.chat(messages, temperature=0.2)
        txt = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not txt or _looks_like_refusal(txt):
            return base_text
        return txt
    except Exception as e:  # noqa: BLE001
        return f"[narrative_unavailable] LLM 错误：{e}\n\n" + base_text
