"""tests/test_phase0_fixes.py — Phase 0 regression tests for B-16, B-18, B-26.

These tests are intentionally stateless (no DB calls) or use in-memory DBs
so they are always fast and deterministic.
"""
import hmac
import hashlib
import pytest
from datetime import datetime, timezone


# ── B-18: core.time ──────────────────────────────────────────────────────────

def test_utcnow_is_aware():
    from core.time import utcnow
    now = utcnow()
    assert now.tzinfo is not None, "utcnow() must return a tz-aware datetime"
    assert now.tzinfo == timezone.utc or str(now.tzinfo) in ("+00:00", "UTC")


def test_ensure_utc_naive_gets_utc():
    from core.time import ensure_utc
    naive = datetime(2024, 6, 1, 12, 0, 0)
    aware = ensure_utc(naive)
    assert aware.tzinfo is not None
    assert aware.year == 2024 and aware.month == 6


def test_ensure_utc_aware_stays_utc():
    from core.time import ensure_utc
    from datetime import timedelta, timezone
    tz_plus5 = timezone(timedelta(hours=5, minutes=30))
    dt_plus5 = datetime(2024, 6, 1, 17, 30, 0, tzinfo=tz_plus5)
    result = ensure_utc(dt_plus5)
    assert result.tzinfo == timezone.utc
    assert result.hour == 12  # 17:30 IST → 12:00 UTC


# ── B-26: certificate signing ─────────────────────────────────────────────────

class _FakeRun:
    run_id = "test-run-42"
    domain = "ecommerce"
    action = "get_inventory"
    entity_id = "SKU-100"
    decision = "allow"
    blocked_reason = None
    summary_json = '{"evidence_nodes":[],"checks":[]}'
    created_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_certificate_has_signature():
    from engine.certificate import CertificateBuilder
    cert = CertificateBuilder.build(_FakeRun())
    assert "signature" in cert, "Certificate must include HMAC signature"
    assert len(cert["signature"]) == 64  # SHA-256 hex


def test_certificate_has_kid():
    from engine.certificate import CertificateBuilder
    cert = CertificateBuilder.build(_FakeRun())
    assert cert.get("kid") == "v1"


def test_certificate_verify_passes():
    from engine.certificate import CertificateBuilder
    cert = CertificateBuilder.build(_FakeRun())
    assert CertificateBuilder.verify(cert) is True


def test_certificate_verify_detects_tamper():
    from engine.certificate import CertificateBuilder
    cert = CertificateBuilder.build(_FakeRun())
    tampered = dict(cert)
    tampered["decision"] = "block"  # tamper with decision field
    assert CertificateBuilder.verify(tampered) is False


def test_certificate_fingerprint_reproducible():
    from engine.certificate import CertificateBuilder
    a = CertificateBuilder.build(_FakeRun())
    b = CertificateBuilder.build(_FakeRun())
    assert a["sha256_fingerprint"] == b["sha256_fingerprint"]
    assert len(a["sha256_fingerprint"]) == 64


# ── B-16: rate limiting — unit-test the _Bucket logic directly ───────────────
# The RateLimitMiddleware is disabled in APP_ENV=test so live HTTP calls never
# receive 429 mid-suite. We test the token-bucket math in isolation instead.

def test_bucket_allows_up_to_limit():
    from core.ratelimit import _Bucket
    b = _Bucket(5, 60)
    results = [b.consume() for _ in range(5)]
    assert all(allowed for allowed, _ in results), "All 5 requests should be allowed"


def test_bucket_blocks_over_limit():
    from core.ratelimit import _Bucket
    b = _Bucket(5, 60)
    for _ in range(5):
        b.consume()
    allowed, retry = b.consume()
    assert not allowed, "6th request must be blocked"
    assert retry > 0, "retry_after must be positive"


def test_bucket_resets_after_window():
    from core.ratelimit import _Bucket
    import time
    b = _Bucket(2, 0)   # 0-second window expires immediately
    b.consume(); b.consume()
    time.sleep(0.02)    # window has expired
    allowed, _ = b.consume()
    assert allowed, "After window expiry bucket should refill"


def test_rate_limit_middleware_skipped_in_test_mode():
    """In APP_ENV=test the middleware is a no-op — no 429 should be returned."""
    import os
    assert os.getenv("APP_ENV") == "test", "This test must run with APP_ENV=test"
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        for i in range(35):
            r = c.post(
                "/gateway/call",
                json={"domain": "ecommerce", "action": "get_inventory",
                      "payload": {"product_id": f"SKU-RL-{i}"}, "agent_id": f"rl-nolimit-{i}"},
            )
            assert r.status_code != 429, (
                f"Request {i} returned 429 — middleware should be disabled in APP_ENV=test"
            )
