from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple


def is_disallowed(ch: str) -> bool:
    o = ord(ch)
    if ch in ('\n', '\r', '\t'):
        return False
    if o < 32:
        return True
    # Private Use Areas
    if 0xE000 <= o <= 0xF8FF:
        return True
    # BOM / zero-width / soft hyphen / word joiners
    if o in (0xFEFF, 0x200B, 0x200C, 0x200D, 0x2060, 0x00AD):
        return True
    return False


def sanitize_file(path: Path) -> Tuple[int, List[str]]:
    try:
        text = path.read_text(encoding='utf-8')
    except Exception:
        text = path.read_bytes().decode('utf-8', errors='ignore')
    bad = [(i, ord(c)) for i, c in enumerate(text) if is_disallowed(c)]
    if not bad:
        return 0, []
    cleaned = ''.join(ch for ch in text if not is_disallowed(ch))
    path.write_text(cleaned, encoding='utf-8', newline='\n')
    cps = [f"U+{cp:04X}" for _, cp in bad[:10]]
    return len(bad), cps


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='src', help='root directory to scan')
    ap.add_argument('--report', default='store/nonprintable_cleanup_report.json')
    args = ap.parse_args()
    root = Path(args.root)
    out: Dict[str, dict] = {}
    for p in root.rglob('*.py'):
        cnt, cps = sanitize_file(p)
        if cnt:
            out[str(p)] = {'removed_count': cnt, 'first10_codepoints': cps}
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

