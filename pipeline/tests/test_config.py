import pytest

from pipeline.config import database_url

SECRET = "hunter2"


def test_database_url_prefers_unpooled(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@pooled/db")
    monkeypatch.setenv("DATABASE_URL_UNPOOLED", " postgresql://u:p@direct/db\n")
    assert database_url() == "postgresql://u:p@direct/db"


def test_database_url_rejects_missing_scheme_without_echoing_password(monkeypatch):
    monkeypatch.setenv("DATABASE_URL_UNPOOLED", f"neondb_owner:{SECRET}@host/db")
    with pytest.raises(RuntimeError, match="must start with postgresql://") as error:
        database_url()
    assert SECRET not in str(error.value)
