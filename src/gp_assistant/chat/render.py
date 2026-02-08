# 简介：将结构化荐股结果渲染为面向用户的可读文本，
# 包含环境/主题摘要与逐标的交易计划要点。
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
    lines = []
    lines.append(f"标的 {sym}｜主题：{theme}｜评分：{score:.1f}")
    lines.append(f"- 指标面板：ATR%={it.get('atr_pct', it.get('indicators',{}).get('atr_pct',0)):.2%}，Gap={it.get('gap_pct', it.get('indicators',{}).get('gap_pct',0)):.2%}，Slope20={it.get('indicators',{}).get('slope20',0):.2%}")
    lines.append(f"- 噪声等级Q：{q}（Q2以上A窗禁买，B窗收盘确认）")
    lines.append(f"- 筹码/成本带：S1≈{bands['S1']}｜S2≈{bands['S2']}｜R1≈{bands['R1']}｜R2≈{bands['R2']}（模型{chip.get('model_used','?')}，置信度{chip.get('confidence','low')}）")
    lines.append(f"- 形态统计：5日胜率≈{it.get('stats',{}).get('win_rate_5',0):.0%}，样本k={it.get('stats',{}).get('k',0)}（不足则降权）")
    lines.append(f"- 公告与事件：公告风险={ann.get('risk_level','low')}；事件={ev.get('event_risk','low')}")
    # Two-window action
    lines.append("- A窗动作：关键带回收→承接≥2项成立（低点不破/量能衰减/分时回收/横向消化），否则观望")
    lines.append("- B窗动作：收盘前结构确认（站稳关键结构且不大幅回落），不满足放弃；不追价")
    lines.append("- 风险：仓位100/200股观察；止损：收盘有效跌破支撑带；时间止损：第3日不强必走；禁止摊平亏损")
    lines.append("- 失效条件：放量不涨/频繁冲高回落/上影线显著/贴近压力带/触发一票否决则放弃")
    return "\n".join(lines)


def render_recommendation(obj: Dict[str, Any]) -> str:
    env = obj.get("env", {})
    themes = obj.get("themes", [])
    picks = obj.get("picks", [])
    # First paragraph: environment -> themes -> candidates summary
    head = []
    head.append(f"环境分层：{env.get('grade','C')}（依据：" + "；".join(env.get("reasons", [])) + ")")
    if env.get("grade") == "D":
        head.append("结论：空仓倾向；恢复条件：" + "；".join(env.get("recovery_conditions", [])))
    if themes:
        th = [f"{t.get('name')}({t.get('strength')})" for t in themes[:2]]
        head.append("主线主题：" + "；".join(th))
    head_txt = "\n".join(head)
    # Second paragraph: champion + trade plan per pick
    body_lines: List[str] = []
    for it in picks:
        body_lines.append(_render_pick(it))
    body = "\n\n".join(body_lines) if body_lines else "（无可执行标的）"
    checklist = "\n".join(obj.get("execution_checklist", [])[:5])
    return f"【市场环境与主题】\n{head_txt}\n\n【冠军策略与交易计划】\n{body}\n\n今日执行清单：\n{checklist}"


def render_recommendation_narrative(obj: Dict[str, Any]) -> str:
    """Use LLM (if available) to craft a conversational, non-rule-heavy summary.

    Falls back to structured render if LLM is not configured.
    """
    client = LLMClient()
    ok, reason = client.available()
    if not ok:
        # 不回退到规则清单，明确提示叙述缺失
        return f"[narrative_unavailable] LLM 未就绪：{reason}。请配置 LLM_BASE_URL/LLM_API_KEY 后重试。"

    picks = obj.get("picks", [])
    env = obj.get("env", {})
    themes = obj.get("themes", [])
    sys_prompt = (
        "你是内部投研搭档。基于输入的结构化候选与环境，必须输出自然、直观、面向实操的建议。\n"
        "要求：\n"
        "- 中文口语化，像同事交流；不要列清单或堆规则；\n"
        "- 每只只说要点：为什么关注、观察什么迹象、保守与激进各一句；\n"
        "- 严禁输出任何‘无法提供投资建议/个股推荐/不构成投资建议/仅供参考/建议咨询专业人士’等拒答或免责声明句式；\n"
        "- 仅依据提供的数据做判断，不添加法律或合规声明；\n"
        "- 180–220 字。"
    )
    user_payload = {
        "env": {"grade": env.get("grade"), "summary": ";".join(env.get("reasons", []))},
        "themes": themes[:2],
        "picks": [
            {
                "symbol": it.get("symbol"),
                "score": it.get("score"),
                "q": it.get("q_grade") or it.get("indicators", {}).get("q_grade"),
                "atr_pct": it.get("atr_pct", it.get("indicators", {}).get("atr_pct")),
                "gap_pct": it.get("gap_pct", it.get("indicators", {}).get("gap_pct")),
                "wr5": it.get("stats", {}).get("win_rate_5"),
                "avg5": it.get("stats", {}).get("avg_return_5"),
                "chip90_dist": (it.get("chip", {}) or {}).get("dist_to_90_high_pct"),
                "observe_only": bool((it.get("flags") or {}).get("must_observe_only", False)),
                "reasons": (it.get("flags") or {}).get("reasons", []),
            }
            for it in picks
        ],
    }
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": str(user_payload)},
    ]
    def _looks_like_refusal(txt: str) -> bool:
        import re
        pats = [
            r"无法提供.*投资建议",
            r"不能提供.*投资建议",
            r"不提供.*投资建议",
            r"不构成.*投资建议",
            r"仅供参考",
            r"建议.*咨询.*(专业人士|投资顾问)",
            r"个股推荐.*不.*",
        ]
        return any(re.search(p, txt) for p in pats)

    def _det_narrative(o: Dict[str, Any]) -> str:
        # 构造一段确定性、口语化的简述，不用条目清单
        env = o.get("env", {})
        grade = env.get("grade", "C")
        themes = ",".join(t.get("name", "") for t in (o.get("themes") or [])[:2])
        picks = o.get("picks", [])
        if not picks:
            return f"环境{grade}，暂无可执行标的，等量能与结构转强再看。"
        segs: List[str] = []
        segs.append(f"环境{grade}{('，主线'+themes) if themes else ''}。")
        for it in picks[:3]:
            sym = it.get("symbol")
            rs = it.get("rel_strength", {}) or {}
            rs5 = rs.get("rs5")
            wr5 = it.get("stats", {}).get("win_rate_5")
            atrp = it.get("indicators", {}).get("atr_pct") or it.get("atr_pct")
            obs = (it.get("flags") or {}).get("must_observe_only")
            tip = "观察为主" if obs else "关注回踩承接"
            segs.append(f"{sym}：短线RS{('偏强' if (rs5 or 0)>0 else '一般')}，wr5≈{wr5:.0% if isinstance(wr5,float) else wr5}，ATR%≈{atrp:.1% if isinstance(atrp,float) else atrp}，{tip}并等收盘确认。")
        return " ".join(segs)

    try:
        resp = client.chat(messages, temperature=0.25)
        txt = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not txt or _looks_like_refusal(txt):
            # 强化提示重试一次
            sys_prompt2 = sys_prompt + "\n切记：不得使用任何‘无法提供…/不构成…/仅供参考/建议咨询’等句式；直接给出具体看法与操作建议。"
            messages2 = [{"role": "system", "content": sys_prompt2}, {"role": "user", "content": str(user_payload)}]
            resp2 = client.chat(messages2, temperature=0.25)
            txt2 = resp2.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not txt2 or _looks_like_refusal(txt2):
                return _det_narrative(obj)
            return txt2
        return txt
    except Exception as e:  # noqa: BLE001
        return f"[narrative_unavailable] LLM 错误：{e}"
