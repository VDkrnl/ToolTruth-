"""
Integration tests using FastAPI's TestClient.

These cover the areas the original suite had no coverage for at all
(see BUG_REPORT.md #8): the login flow, the upload validation/MIME-bypass
path, the publish duplicate guard, is_latest promotion on version delete,
and the local file-serve endpoint. Several tests are direct regression
tests for bugs #2, #3, #4 and #5 from that report.
"""
import io
import os

import pytest
from fastapi.testclient import TestClient

from main import app
from database import SessionLocal
from models import Admin
from auth import hash_password

ADMIN_USER = "test-admin"
ADMIN_PASS = "correct-horse-battery-staple"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_token(client):
    db = SessionLocal()
    try:
        db.add(Admin(username=ADMIN_USER, password_hash=hash_password(ADMIN_PASS)))
        db.commit()
    finally:
        db.close()
    r = client.post("/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---------------------------------------------------------------- auth ----

def test_login_success(client):
    db = SessionLocal()
    try:
        db.add(Admin(username="alice", password_hash=hash_password("s3cret!")))
        db.commit()
    finally:
        db.close()
    r = client.post("/auth/login", json={"username": "alice", "password": "s3cret!"})
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"
    assert r.json()["access_token"]


def test_login_wrong_password(client):
    db = SessionLocal()
    try:
        db.add(Admin(username="bob", password_hash=hash_password("right-pass")))
        db.commit()
    finally:
        db.close()
    r = client.post("/auth/login", json={"username": "bob", "password": "wrong-pass"})
    assert r.status_code == 401


def test_login_unknown_user(client):
    r = client.post("/auth/login", json={"username": "nobody", "password": "x"})
    assert r.status_code == 401


def test_protected_route_requires_token(client):
    r = client.post("/uploads", files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code in (401, 403)


def test_protected_route_rejects_bad_token(client):
    r = client.get("/gateway/events", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


# -------------------------------------------------------------- uploads ---

def test_upload_valid_pdf(client, auth_headers):
    r = client.post(
        "/uploads",
        headers=auth_headers,
        files={"file": ("report.pdf", b"%PDF-1.4 fake pdf body", "application/pdf")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "report.pdf"
    assert body["preview_ready"] is True


def test_upload_rejects_bad_extension(client, auth_headers):
    r = client.post(
        "/uploads",
        headers=auth_headers,
        files={"file": ("malware.exe", b"MZ...", "application/pdf")},
    )
    assert r.status_code == 400


def test_upload_rejects_mime_extension_mismatch(client, auth_headers):
    # Regression test for bug #2: an .exe with a spoofed PDF content-type
    # used to pass validation because the check used OR instead of AND.
    r = client.post(
        "/uploads",
        headers=auth_headers,
        files={"file": ("malware.exe", b"MZ fake binary", "application/pdf")},
    )
    assert r.status_code == 400
    # Also try the inverse: a real extension with a disallowed content-type.
    r2 = client.post(
        "/uploads",
        headers=auth_headers,
        files={"file": ("notes.pdf", b"not really a pdf", "application/x-msdownload")},
    )
    assert r2.status_code == 400


def test_upload_rejects_oversized_file(client, auth_headers, monkeypatch):
    monkeypatch.setenv("MAX_FILE_SIZE_MB", "0")
    import routers.uploads as uploads_module
    monkeypatch.setattr(uploads_module, "MAX", 10)  # 10 bytes
    r = client.post(
        "/uploads",
        headers=auth_headers,
        files={"file": ("report.pdf", b"%PDF-1.4" * 100, "application/pdf")},
    )
    assert r.status_code == 413


def test_upload_cleans_up_orphan_on_failed_conversion(client, auth_headers, monkeypatch, tmp_path):
    # Regression test for bug #3: if PowerPoint conversion fails, the
    # already-saved original must not be left behind with no DB record.
    import routers.uploads as uploads_module

    def fake_convert(data, filename):
        raise RuntimeError("LibreOffice is not installed")

    monkeypatch.setattr(uploads_module, "_convert_presentation_to_pdf", fake_convert)

    r = client.post(
        "/uploads",
        headers=auth_headers,
        files={"file": ("deck.pptx", b"fake pptx bytes", "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
    )
    assert r.status_code == 503
    # Nothing should be left on disk under the (redirected) uploads root.
    leftover_files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert leftover_files == []

    from models import UploadLog
    db = SessionLocal()
    try:
        assert db.query(UploadLog).filter(UploadLog.filename == "deck.pptx").first() is None
    finally:
        db.close()


# -------------------------------------------------------------- publish ---

def _upload_pdf(client, auth_headers, name="doc.pdf"):
    r = client.post(
        "/uploads",
        headers=auth_headers,
        files={"file": (name, b"%PDF-1.4 body", "application/pdf")},
    )
    assert r.status_code == 200
    return r.json()["id"]


def test_publish_happy_path(client, auth_headers):
    upload_id = _upload_pdf(client, auth_headers)
    r = client.post(
        "/publish",
        headers=auth_headers,
        json={
            "upload_id": upload_id, "slug": "planning", "title": "Q1 plan",
            "version": "v1", "date": "2026-01-01", "authors": "Team",
            "summary": "First cut.",
        },
    )
    assert r.status_code == 200
    assert r.json()["slug"] == "planning"


def test_publish_rejects_duplicate(client, auth_headers):
    # Regression test for bug #5: publishing the same upload twice used to
    # silently create a second Version row instead of being rejected.
    upload_id = _upload_pdf(client, auth_headers)
    body = {
        "upload_id": upload_id, "slug": "planning", "title": "Q1 plan",
        "version": "v1", "date": "2026-01-01", "authors": "Team",
        "summary": "First cut.",
    }
    first = client.post("/publish", headers=auth_headers, json=body)
    assert first.status_code == 200
    second = client.post("/publish", headers=auth_headers, json=body)
    assert second.status_code == 409

    from models import Version
    db = SessionLocal()
    try:
        assert db.query(Version).filter(Version.upload_id == upload_id).count() == 1
    finally:
        db.close()


# ----------------------------------------------------------- versions -----

def test_delete_latest_version_promotes_sibling(client, auth_headers):
    # Regression test for bug #4: deleting the is_latest version used to
    # leave the slug with no latest version at all.
    upload_a = _upload_pdf(client, auth_headers, "a.pdf")
    r1 = client.post(
        "/publish", headers=auth_headers,
        json={"upload_id": upload_a, "slug": "roadmap", "title": "Roadmap v1",
              "version": "v1", "date": "2026-01-01", "authors": "Team", "summary": "s"},
    )
    v1_id = r1.json()["id"]

    upload_b = _upload_pdf(client, auth_headers, "b.pdf")
    r2 = client.post(
        "/publish", headers=auth_headers,
        json={"upload_id": upload_b, "slug": "roadmap", "title": "Roadmap v2",
              "version": "v2", "date": "2026-02-01", "authors": "Team", "summary": "s"},
    )
    v2_id = r2.json()["id"]

    # v2 is now is_latest; delete it and confirm v1 gets promoted.
    d = client.delete(f"/versions/{v2_id}", headers=auth_headers)
    assert d.status_code == 200

    remaining = client.get("/versions/roadmap").json()
    assert len(remaining) == 1
    assert remaining[0]["id"] == v1_id
    assert remaining[0]["is_latest"] is True


def test_delete_non_latest_version_leaves_latest_intact(client, auth_headers):
    upload_a = _upload_pdf(client, auth_headers, "a.pdf")
    r1 = client.post(
        "/publish", headers=auth_headers,
        json={"upload_id": upload_a, "slug": "notes", "title": "Notes v1",
              "version": "v1", "date": "2026-01-01", "authors": "Team", "summary": "s"},
    )
    v1_id = r1.json()["id"]

    upload_b = _upload_pdf(client, auth_headers, "b.pdf")
    r2 = client.post(
        "/publish", headers=auth_headers,
        json={"upload_id": upload_b, "slug": "notes", "title": "Notes v2",
              "version": "v2", "date": "2026-02-01", "authors": "Team", "summary": "s"},
    )
    v2_id = r2.json()["id"]

    d = client.delete(f"/versions/{v1_id}", headers=auth_headers)
    assert d.status_code == 200

    remaining = client.get("/versions/notes").json()
    assert len(remaining) == 1
    assert remaining[0]["id"] == v2_id
    assert remaining[0]["is_latest"] is True


def test_delete_version_requires_auth(client, auth_headers):
    upload_a = _upload_pdf(client, auth_headers, "a.pdf")
    r1 = client.post(
        "/publish", headers=auth_headers,
        json={"upload_id": upload_a, "slug": "secure", "title": "Secure v1",
              "version": "v1", "date": "2026-01-01", "authors": "Team", "summary": "s"},
    )
    v1_id = r1.json()["id"]
    r = client.delete(f"/versions/{v1_id}")
    assert r.status_code in (401, 403)


# --------------------------------------------------------------- files ----

def test_file_serve_missing_file(client):
    r = client.get("/files/serve/does-not-exist.pdf")
    assert r.status_code == 404


def test_file_serve_path_traversal_blocked(client):
    r = client.get("/files/serve/../../../../etc/passwd")
    assert r.status_code in (404, 400)


# -------------------------------------------------------------- gateway ---

def test_gateway_call_public_but_domain_restricted(client):
    r = client.post(
        "/gateway/call",
        json={"domain": "not-a-real-domain", "action": "noop", "payload": {}},
    )
    assert r.status_code == 400


def test_gateway_call_public_known_domain(client):
    r = client.post(
        "/gateway/call",
        json={"domain": "ecommerce", "action": "get_inventory",
              "payload": {"product_id": "SKU-100"}, "agent_id": "test-public-caller"},
    )
    assert r.status_code == 200
    assert r.json()["allowed"] is True


def test_gateway_events_requires_auth(client):
    r = client.get("/gateway/events")
    assert r.status_code in (401, 403)
