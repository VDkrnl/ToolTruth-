"""
Shared pytest fixtures for the backend test suite.

Bug fix (see BUG_REPORT.md #10): tests used to share whichever tooltruth.db
happened to be on disk, and only partially cleaned up EvidenceNode rows.
Leftover EventLog/Version/UploadLog/Admin rows from previous runs (or from
manually poking the API while developing) could make test_duplicate_action
_detected and test_benchmark_baselines_differ pass or fail depending on
history, not on the code under test.

This fixture points the app at a fresh temp-file SQLite database for the
whole test session (created before any test module imports `database`,
so every module sees the same isolated engine) and fully truncates every
table before each individual test runs.
"""
import os
import tempfile

import pytest

_tmp_dir = tempfile.TemporaryDirectory(prefix="tooltruth-test-db-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp_dir.name, 'test.db')}"
os.environ.setdefault("JWT_SECRET", "test-secret-for-pytest-only")


@pytest.fixture(autouse=True)
def isolated_local_storage(tmp_path, monkeypatch):
    """Redirect local file storage to a per-test temp dir so test runs never
    leave files behind under backend/uploads/."""
    import storage
    monkeypatch.setattr(storage, "LOCAL_ROOT", tmp_path)
    yield


@pytest.fixture(autouse=True)
def clean_db():
    """Reset all tables to empty before every test."""
    from database import SessionLocal, init_db
    from models import Admin, UploadLog, Version, BenchmarkRun
    from gateway.models import EventLog, EvidenceNode, EvidenceEdge

    init_db()
    db = SessionLocal()
    try:
        for model in (EvidenceEdge, EvidenceNode, EventLog, BenchmarkRun, Version, UploadLog, Admin):
            db.query(model).delete()
        db.commit()
    finally:
        db.close()
    yield
