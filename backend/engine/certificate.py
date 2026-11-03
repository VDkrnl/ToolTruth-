import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

# B-26: Certificate version — keep in sync with main.py app version.
VERSION = "2.0.0"

# B-26: Signing key — set CERT_SIGNING_KEY in environment for production.
# Falls back to a fixed development key so tests never crash on a missing env var.
_SIGNING_KEY = os.getenv("CERT_SIGNING_KEY", "tooltruth-dev-signing-key-change-in-prod").encode()


def _hmac_sign(canonical: str) -> str:
    """Return HMAC-SHA256 hex digest of *canonical* using the configured signing key."""
    return hmac.new(_SIGNING_KEY, canonical.encode(), hashlib.sha256).hexdigest()


class CertificateBuilder:
    verifier_version = VERSION
    schema_version = "1.0"

    @classmethod
    def build(cls, run):
        summary = json.loads(run.summary_json or "{}")
        evidence = summary.get("evidence_nodes", [])
        checks = summary.get("checks", [])
        payload = {
            "certificate_id": f"CERT-{run.run_id}",
            "run_id": run.run_id,
            "kid": "v1",  # B-26: key identifier for rotation support
            "timestamp": (run.created_at if getattr(run, "created_at", None) else datetime.now(timezone.utc)).isoformat(),
            "domain": run.domain,
            "action": run.action,
            "entity_id": run.entity_id,
            "decision": run.decision,
            "blocked_reason": run.blocked_reason,
            "evidence": [
                {
                    "node_id": n.get("id"),
                    "claim": n.get("claim"),
                    "source": n.get("source"),
                    "confidence": n.get("confidence"),
                    "timestamp": n.get("timestamp"),
                    "age_at_decision_seconds": cls._age_at(n.get("timestamp"), summary.get("decision_timestamp")),
                    "freshness_status": cls._freshness_at(n.get("timestamp"), summary.get("decision_timestamp"), n.get("freshness_ttl_seconds", 300)),
                } for n in evidence
            ],
            "rules": [
                {"name": c.get("name"), "outcome": "passed" if c.get("passed") else "failed",
                 "reason": c.get("reason")} for c in checks
            ],
            "state_version_before": summary.get("state_version_before"),
            "state_version_after": summary.get("state_version_after"),
            "verifier_version": cls.verifier_version,
            "schema_version": cls.schema_version,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        payload["sha256_fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()
        # B-26: HMAC signature so downstream verifiers can detect tampering.
        payload["signature"] = _hmac_sign(canonical)
        return payload

    @classmethod
    def verify(cls, cert: dict) -> bool:
        """Return True if *cert* has a valid HMAC signature.

        The signature covers the canonical JSON of all fields *except*
        ``sha256_fingerprint`` and ``signature`` themselves.
        """
        try:
            to_sign = {k: v for k, v in cert.items() if k not in ("sha256_fingerprint", "signature")}
            canonical = json.dumps(to_sign, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            expected = _hmac_sign(canonical)
            return hmac.compare_digest(expected, cert.get("signature", ""))
        except Exception:
            return False

    @staticmethod
    def _age_at(ts, decision_ts):
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            decision = datetime.fromisoformat(str(decision_ts).replace("Z", "+00:00"))
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            if decision.tzinfo is None: decision = decision.replace(tzinfo=timezone.utc)
            return max(0, int((decision - dt).total_seconds()))
        except Exception:
            return None

    @classmethod
    def _freshness_at(cls, ts, decision_ts, ttl):
        age = cls._age_at(ts, decision_ts)
        if age is None: return "invalid"
        return "fresh" if age <= int(ttl) else "stale"



@dataclass(frozen=True)
class DecisionCertificate:
    certificate_id: str
    run_id: str
    timestamp: str
    domain: str
    action: str
    entity_id: str
    decision: str
    evidence: list
    rules: list
    state_version_before: str | None
    state_version_after: str | None
    verifier_version: str
    schema_version: str
    sha256_fingerprint: str
