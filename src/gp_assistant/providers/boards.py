from __future__ import annotations

from typing import Literal


def _norm_ts_code(s: str) -> tuple[str, str]:
    s = (s or "").strip().upper()
    if "." in s:
        code, exch = s.split(".")
        return code.zfill(6), exch
    # plain 6-digit -> infer exchange by leading digit; 6* -> SH else SZ
    code = s.zfill(6)
    exch = "SH" if code.startswith("6") else "SZ"
    return code, exch


def classify_board(ts_code: str) -> Literal["MAIN", "STAR", "CHINEXT", "B", "OTHER"]:
    """Classify A-share board strictly by code system (AkShare-compatible, no heuristics).

    Rules (documented by SSE/SZSE code allocations):
    - SH Main: 600/601/603/605
    - SH STAR: 688
    - SH B: 900
    - SZ Main: 000/001/002/003
    - SZ ChiNext: 300/301
    - SZ B: 200
    Everything else -> OTHER
    """
    code, exch = _norm_ts_code(ts_code)
    p3 = code[:3]
    if exch == "SH":
        if p3 in {"600", "601", "603", "605"}:
            return "MAIN"
        if p3 == "688":
            return "STAR"
        if p3 == "900":
            return "B"
        return "OTHER"
    else:  # SZ
        if p3 in {"000", "001", "002", "003"}:
            return "MAIN"
        if p3 in {"300", "301"}:
            return "CHINEXT"
        if p3 == "200":
            return "B"
        return "OTHER"


def is_mainboard(ts_code: str) -> bool:
    return classify_board(ts_code) == "MAIN"

