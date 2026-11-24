import json
import copy
from engine.consistency import ConsistencyEngine
from engine.claim_extractor import ClaimExtractor
from gateway.models import EventLog, EvidenceNode, EvidenceEdge
from domains.ecommerce import EcommerceDomain
from domains.devops import DevOpsDomain
from domains.travel import TravelDomain
from gateway.fault_injector import FaultInjector
from datetime import datetime, timezone


DOMAINS = {"ecommerce": EcommerceDomain, "devops": DevOpsDomain, "travel": TravelDomain}


class ToolCallInterceptor:
    def __init__(self, db, domain=None):
        self.db = db
        self.engine = ConsistencyEngine(db)
        self.extractor = ClaimExtractor()
        self.domains = {k: v() for k, v in DOMAINS.items()} if domain is None else {domain.name: domain}

    @staticmethod
    def entity_id_for(domain, action, payload):
        if domain == "ecommerce":
            return payload.get("product_id", "SKU-100")
        if domain == "devops":
            if action == "deploy":
                return payload.get("deployment_id", "DEP-100")
            return payload.get("issue_id", "ISS-100")
        if domain == "travel":
            return payload.get("booking_id", payload.get("seat_id", "SEAT-12A"))
        return payload.get("entity_id", "unknown")

    def call(self, domain_name, action, payload, agent_id="anonymous", context_snapshot=None, fault_config=None):
        if domain_name not in self.domains:
            raise ValueError("Unsupported domain")
        domain = self.domains[domain_name]
        payload = dict(payload or {})
        entity_id = self.entity_id_for(domain_name, action, payload)
        entity = domain.entities.get(entity_id)
        if entity is None and domain_name == "devops" and action == "deploy":
            entity = domain.entities.get(payload.get("deployment_id", "DEP-100"))
            entity_id = entity.id if entity else entity_id

        pre_snapshot = domain.snapshot()
        pre_state = entity.state if entity else None
        injector = FaultInjector(self.db)
        # The injector is the only component allowed to mutate the prototype's
        # domain state before the simulator call.
        injected = injector.validate(fault_config)
        if injected and injected["type"] == "duplicate_action":
            payload["_fault_agent_id"] = agent_id
        payload, injected, fault_context = injector.prepare(domain, action, payload, entity_id, injected)
        # Read the evidence timestamp after fault preparation so stale evidence
        # is evaluated against the deliberately back-dated observation.
        entity = domain.entities.get(entity_id)
        source_timestamp = entity.updated_at if entity else None

        try:
            prior_nodes = self.db.query(EvidenceNode).filter(
                EvidenceNode.entity_id == entity_id
            ).order_by(EvidenceNode.id.asc()).all()
            historical = []
            for node in prior_nodes:
                if "=" in node.claim:
                    field, value = node.claim.split("=", 1)
                    try: value = json.loads(value)
                    except Exception:
                        pass
                    if node.source in {"benchmark", "external", "tool"}:
                        historical.append({"field": field, "value": value, "source": node.source})

            schema_check = self.engine.check_schema(domain.name, action, payload)
            if not schema_check.passed:
                checks = [schema_check]
                decision = self.engine.produce_decision(checks)
                result_data = {"error": "schema_error", "entity_id": entity_id}
                report_checks = checks
                evidence = []
                fault_type = "schema_error"
                blocked_reason = schema_check.reason
            else:
                result = domain.simulate_tool_call(action, payload)
                target_state = result.data.get("state") or result.data.get("status") or domain.target_state_for_action(action)
                if domain_name == "devops" and action == "deploy" and payload.get("environment", "staging") != "prod":
                    target_state = None

                # Fault-specific observations are checks, not trusted instructions.
                effective_context = dict(context_snapshot or {})
                effective_context.update(fault_context)
                report = self.engine.run_all(
                    domain, action, payload, result.data, effective_context,
                    entity_id=entity_id, agent_id=agent_id, entity_state=pre_state,
                    target_state=target_state, historical_claims=historical,
                    source_timestamp=source_timestamp,
                )
                report_checks = list(report.checks)
                fault_type = report.fault_type
                blocked_reason = report.blocked_reason
                result_data = result.data

                if injected:
                    ftype = injected["type"]
                    if ftype == "missing_update":
                        report_checks.append(__import__("engine.schemas", fromlist=["CheckResult"]).CheckResult(
                            name="missing_update", passed=False,
                            reason=f"Required state field '{fault_context.get('_fault_missing_update')}' was removed."))
                    elif ftype == "out_of_order":
                        report_checks.append(__import__("engine.schemas", fromlist=["CheckResult"]).CheckResult(
                            name="ordering", passed=False,
                            reason="Injected evidence events are out of causal order."))
                    elif ftype == "race_condition":
                        report_checks.append(__import__("engine.schemas", fromlist=["CheckResult"]).CheckResult(
                            name="race_condition", passed=False,
                            reason="Concurrent reserve/sell operations observed on the same entity."))
                    elif ftype == "partial_failure":
                        report_checks.append(__import__("engine.schemas", fromlist=["CheckResult"]).CheckResult(
                            name="partial_failure", passed=False,
                            reason="First mutation succeeded but the downstream payment step failed; compensation was required."))
                    elif ftype == "invalid_transition":
                        report_checks.append(__import__("engine.schemas", fromlist=["CheckResult"]).CheckResult(
                            name="state_transition", passed=False,
                            reason=f"Injected invalid state makes action '{action}' illegal."))
                    # Re-run the deterministic decision after the fault-specific check.
                    decision = self.engine.produce_decision(report_checks)
                    if not report_checks[-1].passed:
                        fault_type = ftype
                        blocked_reason = report_checks[-1].reason
                else:
                    decision = report.decision

                claims = self.extractor.extract(result_data)
                evidence = []
                for c in claims:
                    try:
                        node_ts = datetime.fromisoformat(str(c.get("timestamp")).replace("Z", "+00:00"))
                        if node_ts.tzinfo is None:
                            node_ts = node_ts.replace(tzinfo=timezone.utc)
                    except Exception:
                        node_ts = datetime.now(timezone.utc)
                    node = EvidenceNode(
                        node_type="claim", entity_id=entity_id, claim=c["claim"],
                        source=c["source"], confidence=str(c["confidence"]),
                        schema_version="1.0", timestamp=node_ts
                    )
                    self.db.add(node); self.db.flush()
                    evidence.append({"id": node.id, "claim": node.claim, "source": node.source,
                                     "timestamp": node.timestamp.isoformat(), "confidence": node.confidence})
                    if prior_nodes:
                        self.db.add(EvidenceEdge(from_node_id=prior_nodes[-1].id,
                                                 to_node_id=node.id, relation_type="supercedes"))
                    if fault_type == "contradiction" and injected and injected["type"] == "contradictory_observation":
                        self.db.add(EvidenceEdge(from_node_id=prior_nodes[-1].id, to_node_id=node.id,
                                                 relation_type="contradicts")) if prior_nodes else None

                if injected and injected["type"] == "partial_failure":
                    # The simulator mutation is compensated before the request finishes.
                    domain.restore(pre_snapshot)
                    result_data = {**result_data, "error": "partial_failure_compensated", "compensated": True}
                blocked_reason = blocked_reason or (next((c.reason for c in report_checks if not c.passed), None))

            allowed = decision == "allow"
            post_state = domain.entities.get(entity_id).state if domain.entities.get(entity_id) else None
            row = EventLog(
                domain=domain_name, action=action, payload_json=json.dumps(payload, sort_keys=True),
                result_json=json.dumps(result_data), agent_id=agent_id,
                status="allowed" if allowed else "blocked",
                reason=blocked_reason or "Checks passed.", dependencies_json="[]"
            )
            self.db.add(row)
            self.db.commit()
            return {
                "allowed": allowed, "decision": decision, "result": result_data,
                "reason": blocked_reason or "All consistency checks passed.",
                "fault_type": fault_type, "evidence_trail": evidence,
                "checks": [c.model_dump() for c in report_checks],
                "pre_state": pre_state, "post_state": post_state,
                "state_version_before": self._state_version(domain, entity_id, pre_snapshot),
                "state_version_after": self._state_version(domain, entity_id, domain.snapshot()),
            }
        finally:
            # Prototype simulations are isolated: no injected entity mutation survives.
            domain.restore(pre_snapshot)

    @staticmethod
    def _state_version(domain, entity_id, snapshot):
        if not entity_id or entity_id not in snapshot:
            return None
        import hashlib
        canonical = json.dumps(snapshot[entity_id], sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:12]
