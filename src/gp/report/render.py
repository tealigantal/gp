from __future__ import annotations

from typing import Dict, Any


def render_markdown(report: Dict[str, Any]) -> str:
    # Basic human-readable rendering following the two-block structure
    lines = []
    lines.append(f"# 市场环境 → 主题池 → 候选池 ({report['date']})")
    lines.append("")
    lines.append(f"环境：{report['market_env']}  主题：{', '.join(report.get('main_themes', []))}")
    cps = report.get('candidate_pool_summary', {})
    if cps:
        lines.append(f"候选池：共{cps.get('count', '?')}支；统计窗口：{cps.get('window', 'N/A')}")
    lines.append("")
    lines.append("Top10：")
    for i, it in enumerate(report.get('top10', []), 1):
        ind = it.get('indicators', {})
        lines.append(f"{i}. {it['code']} Q{it.get('q_level', 0)} RSI2={ind.get('rsi2')}, BIAS6={ind.get('bias6')}, ATR%={ind.get('atrp')}")
    lines.append("")
    lines.append("# 冠军策略 → 交易计划")
    ch = report.get('champion', {})
    lines.append(f"冠军：{ch.get('id', 'N/A')}，理由：{ch.get('reason', 'N/A')}")
    lines.append("执行清单：")
    for x in report.get('action_list', []):
        lines.append(f"- {x}")
    lines.append("")
    lines.append(report.get('disclaimer', ''))
    return "\n".join(lines)

