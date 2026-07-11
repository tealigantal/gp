from __future__ import annotations

import os
import tempfile
import math
from pathlib import Path
from typing import Optional

from ..contracts.objects import (
    AdviceRun,
    CurrentSlotPointer,
    DayBook,
    LiveSlotArtifact,
    MarketBook,
)
from ..core.paths import store_dir
from ..runtime.producer import assert_producer_compatible, producer_is_compatible


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _book_root() -> Path:
    p = store_dir() / "book"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _run_root() -> Path:
    p = Path(os.getenv("GP_RUNS_DIR") or str(store_dir() / "runs"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _daybook_root() -> Path:
    p = _book_root() / "daybooks"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _slot_root() -> Path:
    p = _book_root() / "slots"
    p.mkdir(parents=True, exist_ok=True)
    return p


def current_book_path() -> Path:
    return _book_root() / "current.json"


def current_pointer_path() -> Path:
    return _book_root() / "current_slot.json"


def versioned_book_path(trading_day: str, book_version: str) -> Path:
    p = _book_root() / trading_day
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{book_version}.json"


def daybook_path(trading_day: str) -> Path:
    return _daybook_root() / f"{trading_day}.json"


def slot_artifact_path(trade_day: str, artifact_id: str) -> Path:
    p = _slot_root() / trade_day
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{artifact_id}.json"


def save_daybook(daybook: DayBook) -> None:
    assert_producer_compatible(daybook.producer, stage="daybook")
    _atomic_write_text(daybook_path(daybook.trading_day), daybook.model_dump_json(indent=2))


def load_daybook(trading_day: str | None) -> Optional[DayBook]:
    if not trading_day:
        return None
    p = daybook_path(trading_day)
    if not p.exists():
        return None
    try:
        return DayBook.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_latest_daybook() -> Optional[DayBook]:
    files = sorted(_daybook_root().glob("*.json"))
    if not files:
        return None
    try:
        return DayBook.model_validate_json(files[-1].read_text(encoding="utf-8"))
    except Exception:
        return None


def load_latest_saved_book(trading_day: str | None = None) -> Optional[MarketBook]:
    roots: list[Path]
    if trading_day:
        day_root = _book_root() / trading_day
        roots = [day_root] if day_root.exists() else []
    else:
        roots = [p for p in sorted(_book_root().iterdir()) if p.is_dir() and p.name not in {"daybooks", "slots"}]
    files: list[Path] = []
    for root in roots:
        files.extend(sorted(root.glob("*.json")))
    if not files:
        return None
    for path in reversed(files):
        try:
            return MarketBook.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None


def save_slot_artifact(artifact: LiveSlotArtifact) -> None:
    assert_producer_compatible(artifact.producer, stage="slot_artifact")
    _atomic_write_text(slot_artifact_path(artifact.trade_day, artifact.artifact_id), artifact.model_dump_json(indent=2))


def load_slot_artifact(artifact_id: str | None, trade_day: str | None = None) -> Optional[LiveSlotArtifact]:
    if not artifact_id:
        return None
    candidates: list[Path] = []
    if trade_day:
        candidates.append(slot_artifact_path(trade_day, artifact_id))
    else:
        candidates.extend(sorted(_slot_root().glob(f"*/{artifact_id}.json")))
    for p in candidates:
        if not p.exists():
            continue
        try:
            return LiveSlotArtifact.model_validate_json(p.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None


def save_current_pointer(pointer: CurrentSlotPointer) -> None:
    assert_producer_compatible(pointer.producer, stage="current_pointer")
    artifact = load_slot_artifact(pointer.artifact_id, trade_day=pointer.trade_day)
    if artifact is None or not producer_is_compatible(artifact.producer):
        raise RuntimeError("current_pointer_target_incompatible")
    if artifact.trade_day != pointer.trade_day or artifact.slot_id != pointer.slot_id:
        raise RuntimeError("current_pointer_target_mismatch")
    book_version = str(pointer.book_version or pointer.artifact_id)
    book_path = versioned_book_path(pointer.trade_day, book_version)
    if not book_path.exists():
        raise RuntimeError("current_pointer_book_missing")
    try:
        book = MarketBook.model_validate_json(book_path.read_text(encoding="utf-8"))
    except Exception as ex:
        raise RuntimeError("current_pointer_book_invalid") from ex
    if (
        not producer_is_compatible(book.producer)
        or book.book_version != book_version
        or book.artifact_id != pointer.artifact_id
    ):
        raise RuntimeError("current_pointer_book_incompatible")
    _atomic_write_text(current_pointer_path(), pointer.model_dump_json(indent=2))


def load_current_pointer() -> Optional[CurrentSlotPointer]:
    p = current_pointer_path()
    if not p.exists():
        return None
    try:
        return CurrentSlotPointer.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_current_slot_artifact() -> Optional[LiveSlotArtifact]:
    pointer = load_current_pointer()
    if not pointer:
        return None
    if not producer_is_compatible(pointer.producer):
        return None
    artifact = load_slot_artifact(pointer.artifact_id, trade_day=pointer.trade_day)
    if artifact is None or not producer_is_compatible(artifact.producer):
        return None
    return artifact


def compose_market_book(daybook: DayBook, artifact: LiveSlotArtifact) -> MarketBook:
    reason = str((artifact.provider_meta or {}).get("reason") or "").strip()
    data_status = str((artifact.provider_meta or {}).get("data_status") or "").strip()
    if not data_status:
        if reason == "intraday_pulse":
            data_status = "ok" if str(artifact.slot_status or "").upper() == "OK" else "degraded"
        else:
            data_status = "daily_plan"
    return MarketBook(
        trading_day=artifact.trade_day,
        book_version=artifact.artifact_id,
        updated_at=artifact.updated_at,
        regime=daybook.regime,
        daybook=daybook,
        board=artifact.board,
        watchset=list(artifact.tracked_universe.total),
        symbol_states=artifact.symbol_states,
        portfolio_snapshot=artifact.portfolio_snapshot,
        last_closed_5m=artifact.slot_at,
        side_results=artifact.side_results,
        artifact_id=artifact.artifact_id,
        slot_id=artifact.slot_id,
        slot_status=artifact.slot_status,
        publish_allowed=artifact.publish_allowed,
        daybook_effective_day=artifact.daybook_effective_day,
        pulse_trade_day=(artifact.trade_day if artifact.slot_at else None),
        pulse_slot_at=artifact.slot_at,
        market_phase=artifact.market_phase,
        data_status=data_status,
        gate=artifact.gate,
        data_quality=artifact.data_quality,
        tracked_universe=artifact.tracked_universe,
    )


def load_current_book() -> Optional[MarketBook]:
    pointer = load_current_pointer()
    if pointer is None or not producer_is_compatible(pointer.producer):
        return None
    book_version = str(pointer.book_version or pointer.artifact_id)
    path = versioned_book_path(pointer.trade_day, book_version)
    if not path.exists():
        return None
    try:
        book = MarketBook.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if (
        not producer_is_compatible(book.producer)
        or book.book_version != book_version
        or book.artifact_id != pointer.artifact_id
        or book.trading_day != pointer.trade_day
    ):
        return None
    return book


def save_book(book: MarketBook) -> None:
    txt = book.model_dump_json(indent=2)
    _atomic_write_text(current_book_path(), txt)
    _atomic_write_text(versioned_book_path(book.trading_day, book.book_version), txt)


def publish_current_bundle(daybook: DayBook, artifact: LiveSlotArtifact) -> MarketBook:
    assert_producer_compatible(daybook.producer, stage="publish_daybook")
    assert_producer_compatible(artifact.producer, stage="publish_slot")
    if artifact.daybook_effective_day != daybook.trading_day:
        raise RuntimeError("runtime_artifact_trade_day_mismatch")
    allowed = {pick.symbol for pick in [*daybook.picks, *daybook.reserve_picks]}
    if any(entry.symbol not in allowed for entry in artifact.board):
        raise RuntimeError("runtime_artifact_board_outside_daybook")
    pick_symbols = {pick.symbol for pick in daybook.picks}
    if {entry.symbol for entry in artifact.board} != pick_symbols:
        raise RuntimeError("runtime_artifact_board_pick_mismatch")
    if not daybook.picks and str(daybook.source_meta.get("decision") or "") != "no_trade":
        raise RuntimeError("runtime_artifact_empty_without_no_trade")
    for pick in daybook.picks:
        entry_values = [pick.entry_plan.get(key) for key in ("low", "high", "price")]
        stop_values = [pick.stop_plan.get(key) for key in ("price", "stop_price", "low")]
        if not pick.symbol or pick.rank < 1:
            raise RuntimeError("runtime_artifact_pick_identity_invalid")
        if not any(_finite_positive(value) for value in entry_values) or not any(_finite_positive(value) for value in stop_values):
            raise RuntimeError(f"runtime_artifact_trade_plan_missing:{pick.symbol}")
    if any(not math.isfinite(float(entry.final_score)) for entry in artifact.board):
        raise RuntimeError("runtime_artifact_score_non_finite")
    book = compose_market_book(daybook, artifact)
    book.producer = dict(artifact.producer)
    # Pointer is the commit point and therefore must be written last.
    save_daybook(daybook)
    save_slot_artifact(artifact)
    save_book(book)
    save_current_pointer(
        CurrentSlotPointer(
            artifact_id=artifact.artifact_id,
            trade_day=artifact.trade_day,
            slot_id=artifact.slot_id,
            slot_at=artifact.slot_at,
            updated_at=artifact.updated_at,
            book_version=book.book_version,
            producer=dict(artifact.producer),
        )
    )
    return book


def _finite_positive(value) -> bool:
    try:
        number = float(value)
    except Exception:
        return False
    return math.isfinite(number) and number > 0.0


def run_path(run_id: str) -> Path:
    return _run_root() / f"{run_id}.json"


def save_run(run: AdviceRun) -> None:
    run_path(run.run_id).write_text(run.model_dump_json(indent=2), encoding="utf-8")


def load_run(run_id: str | None) -> Optional[AdviceRun]:
    if not run_id:
        return None
    p = run_path(run_id)
    if not p.exists():
        return None
    try:
        return AdviceRun.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception:
        return None
