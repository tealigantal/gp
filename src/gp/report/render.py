from __future__ import annotations

from typing import Dict, Any


def render_markdown(report: Dict[str, Any]) -> str:
    """Render a concise human-readable markdown for a daily report."""
    lines: list[str] = []
    lines.append(f"# 市场环境 · 主题 · 候选池（{report.get('date','-')}）")
    lines.append("")
    lines.append(f"环境：{report.get('market_env','-')}  主题：{', '.join(report.get('main_themes', []))}")
    cps = report.get('candidate_pool_summary', {})
    if cps:
        lines.append(f"候选池：{cps.get('count', '?')} 支；窗口：{cps.get('window', 'N/A')}")
    lines.append("")
    lines.append("## Top10")
    for i, it in enumerate(report.get('top10', []), start=1):
        ind = it.get('indicators', {})
        lines.append(
            f"{i}. {it.get('code','?')}  Q{it.get('q_level', 0)}  "
            f"RSI2={ind.get('rsi2','-')}, BIAS6={ind.get('bias6','-')}, ATR%={ind.get('atrp','-')}"
        )
    lines.append("")
    lines.append("# 冠军策略 · 交易计划")
    ch = report.get('champion', {})
    lines.append(f"冠军：{ch.get('id', 'N/A')}；理由：{ch.get('reason', 'N/A')}")
    lines.append("执行清单：")
    for x in report.get('action_list', []):
        lines.append(f"- {x}")
    lines.append("")
    lines.append(str(report.get('disclaimer', '')).strip())
    return "\n".join(lines)

