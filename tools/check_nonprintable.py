from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator, Tuple


ALLOW = {"\n", "\r", "\t"}


def iter_issues(path: Path) -> Iterator[Tuple[int, int, int, str]]:
    """Yield (line, col, codepoint, line_snippet) for each offending char."""
    text = path.read_text(encoding='utf-8', errors='strict')
    for ln, line in enumerate(text.splitlines(keepends=True), start=1):
        for col, ch in enumerate(line, start=1):
            o = ord(ch)
            if ch in ALLOW:
                continue
            if o < 32:
                yield ln, col, o, line
                continue
            if 0xE000 <= o <= 0xF8FF:
                yield ln, col, o, line
                continue
            if o in (0xFEFF, 0x200B, 0x200C, 0x200D, 0x2060, 0x00AD):
                yield ln, col, o, line


def visualize(line: str, col: int, o: int) -> str:
    vis = []
    for i, ch in enumerate(line.rstrip('\n'), start=1):
        if i == col:
            vis.append(f"<U+{o:04X}>")
        else:
            vis.append(ch if ch in ALLOW or ord(ch) >= 32 else ' ')
    return ''.join(vis)[:120]


def main() -> int:
    root = Path('src')
    failed = False
    for p in root.rglob('*.py'):
        issues = list(iter_issues(p))
        for ln, col, o, line in issues:
            failed = True
            print(f"{p}:{ln}:{col}: non-printable U+{o:04X} : {visualize(line, col, o)}")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

