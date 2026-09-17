import pytest


@pytest.fixture(autouse=True)
def isolated_runtime_store(tmp_path, monkeypatch):
    """Worker preflight tests must never open the developer's live database."""
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path / "store"))
