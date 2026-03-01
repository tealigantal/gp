from __future__ import annotations

from typing import Tuple


def canonicalize_ts_code(s: str) -> Tuple[str, str, str]:
    """Return (ts_code, code6, symbol_display) from various inputs.

    Accepts: 601869 | sh601869 | sz002455 | 600519.SH | 000001.SZ
    Outputs: (XXXXXX.SH|SZ, XXXXXX, same-as-ts_code for display)
    """
    raw = (s or "").strip()
    t = raw.upper().replace(" ", "")
    code = ""
    exch = ""
    # 600519.SH
    if "." in t:
        parts = t.split(".")
        if len(parts) == 2 and parts[0].isdigit() and len(parts[0]) <= 6:
            code = parts[0].zfill(6)
            e = parts[1]
            if e in {"SH", "SZ"}:
                exch = e
    # sh601869 / sz002455
    if not exch and len(t) >= 8 and (t.startswith("SH") or t.startswith("SZ")) and t[2:8].isdigit():
        exch = t[:2]
        code = t[2:8]
    # plain 6-digit -> infer exchange by leading digit (heuristic): 6=SH, 0/3=SZ
    if not exch and t.isdigit() and len(t) == 6:
        code = t
        if t[0] == "6":
            exch = "SH"
        else:
            exch = "SZ"
    # fallback: keep as-is padded
    if not code:
        # attempt to strip non-digits and take last 6
        dd = "".join([c for c in t if c.isdigit()])
        if len(dd) >= 6:
            code = dd[-6:]
            if not exch:
                exch = "SZ" if code[0] != "6" else "SH"
    if not code:
        code = "000000"
    if not exch:
        exch = "SZ"
    ts = f"{code}.{exch}"
    return ts, code, ts

