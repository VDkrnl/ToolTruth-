import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone



class CertificateBuilder:
    verifier_version = "2.1.0"
    schema_version = "1.0"

    @classmethod
    def build(cls, run):
        summary = json.loads(run.summary_json or "{}")
        evidence = summary.get("evidence_nodes", [])
        checks = summary.get("checks", [])
        payload = {
            "certificate_id": f"CERT-{run.run_id}",
            "run_id": run.run_id,
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
        return payload

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
