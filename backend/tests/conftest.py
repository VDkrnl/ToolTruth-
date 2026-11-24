"""
Shared pytest fixtures for the backend test suite.

Every test gets a fresh, empty database (no leftover rows from previous tests or
from manual development sessions).  We redirect the app at a temp-file SQLite
database for the whole session, then truncate every mapped table before each test.
"""
import os
import tempfile

import pytest

_tmp_dir = tempfile.TemporaryDirectory(prefix="tooltruth-test-db-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp_dir.name, 'test.db')}"
os.environ.setdefault("JWT_SECRET", "test-secret-for-pytest-only-at-least-32chars")
os.environ.setdefault("APP_ENV", "test")


@pytest.fixture(autouse=True)
def isolated_local_storage(tmp_path, monkeypatch):
    """Redirect local file storage to a per-test temp dir so test runs never
    leave files behind under backend/uploads/."""
    import storage
    monkeypatch.setattr(storage, "LOCAL_ROOT", tmp_path)
    yield


@pytest.fixture(autouse=True)
def clean_db():
    """Reset ALL tables to empty before every test.

    Uses Base.metadata.sorted_tables in reverse-dependency order so that
    foreign-key constraints (SQLite enforces them when enabled) are satisfied.
    OrderAttempt and ShopifyWebhookEvent are included so idempotency keys
    from a previous test never bleed into the next one.
    """
    from database import SessionLocal, init_db, Base

    init_db()
    db = SessionLocal()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    finally:
        db.close()
    yield
