from __future__ import annotations

from pathlib import Path


ALLOW = {"\n", "\r", "\t"}


def _file_issues(path: Path):
    text = path.read_text(encoding='utf-8')
    for ln, line in enumerate(text.splitlines(keepends=True), start=1):
        for col, ch in enumerate(line, start=1):
            o = ord(ch)
            if ch in ALLOW:
                continue
            if o < 32:
                yield (ln, col, o)
            if 0xE000 <= o <= 0xF8FF:
                yield (ln, col, o)
            if o in (0xFEFF, 0x200B, 0x200C, 0x200D, 0x2060, 0x00AD):
                yield (ln, col, o)


def test_no_nonprintable_chars():
    root = Path('src')
    offenders = []
    for p in root.rglob('*.py'):
        issues = list(_file_issues(p))
        if issues:
            offenders.append((p, issues[:3]))
    assert not offenders, f"Non-printable chars found: {offenders}"

