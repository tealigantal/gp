from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..contracts.objects import MarketBook, AdviceRun
from ..core.paths import store_dir


def _book_root() -> Path:
    p = store_dir() / 'book'
    p.mkdir(parents=True, exist_ok=True)
    return p


def _run_root() -> Path:
    p = store_dir() / 'runs'
    p.mkdir(parents=True, exist_ok=True)
    return p


def current_book_path() -> Path:
    return _book_root() / 'current.json'


def versioned_book_path(trading_day: str, book_version: str) -> Path:
    p = _book_root() / trading_day
    p.mkdir(parents=True, exist_ok=True)
    return p / f'{book_version}.json'


def load_current_book() -> Optional[MarketBook]:
    p = current_book_path()
    if not p.exists():
        return None
    try:
        return MarketBook.model_validate_json(p.read_text(encoding='utf-8'))
    except Exception:
        return None


def save_book(book: MarketBook) -> None:
    txt = book.model_dump_json(indent=2)
    current_book_path().write_text(txt, encoding='utf-8')
    versioned_book_path(book.trading_day, book.book_version).write_text(txt, encoding='utf-8')


def run_path(run_id: str) -> Path:
    return _run_root() / f'{run_id}.json'


def save_run(run: AdviceRun) -> None:
    run_path(run.run_id).write_text(run.model_dump_json(indent=2), encoding='utf-8')


def load_run(run_id: str | None) -> Optional[AdviceRun]:
    if not run_id:
        return None
    p = run_path(run_id)
    if not p.exists():
        return None
    try:
        return AdviceRun.model_validate_json(p.read_text(encoding='utf-8'))
    except Exception:
        return None
