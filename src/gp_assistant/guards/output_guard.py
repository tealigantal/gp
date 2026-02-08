# 简介：输出安全守护。对渲染文本进行简单敏感词/格式校验，返回安全文本与标记。
from __future__ import annotations

import re
from typing import Tuple


_TRIGGER_PATTERNS = [
    r"到\s*\d+(?:\.\d+)?元(?:买|买入)",
    r">=\s*\d+(?:\.\d+)?",
    r"突破\s*\d+(?:\.\d+)?(元)?(就|立刻)?买",
    r"挂单|条件单|触发价|市价单立刻",
    r"站上\s*\d+(?:\.\d+)?(元)?(就|立刻)?买",
]


def guard(text: str) -> Tuple[bool, str]:
    """Check and auto-rewrite forbidden trigger expressions.

    Returns: (ok, possibly_rewritten_text)
    """
    bad = False
    out = text
    for pat in _TRIGGER_PATTERNS:
        if re.search(pat, out):
            bad = True
            out = re.sub(pat, "满足关键结构后执行（去数值触发）", out)
    # If still risky, append downgrade note
    if bad and "【文本合规降级】" not in out:
        out += "\n【文本合规降级】已移除数值触发表达，仅保留结构条件；不满足则观望。"
    return (not bad, out)
