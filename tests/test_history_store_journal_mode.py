from gp_assistant.search import history_store


def test_history_journal_mode_defaults_to_wal(monkeypatch):
    monkeypatch.delenv("GP_HISTORY_SQLITE_JOURNAL_MODE", raising=False)
    assert history_store._sqlite_journal_mode() == "WAL"


def test_history_journal_mode_accepts_delete_case_insensitively(monkeypatch):
    monkeypatch.setenv("GP_HISTORY_SQLITE_JOURNAL_MODE", " delete ")
    assert history_store._sqlite_journal_mode() == "DELETE"


def test_history_journal_mode_rejects_untrusted_pragma(monkeypatch):
    monkeypatch.setenv("GP_HISTORY_SQLITE_JOURNAL_MODE", "WAL; DROP TABLE items")
    assert history_store._sqlite_journal_mode() == "WAL"


def test_history_database_filename_cannot_escape_store(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path))
    monkeypatch.setenv("GP_HISTORY_SQLITE_FILENAME", "../outside.db")
    assert history_store._db_path() == tmp_path / "search" / "history.db"
