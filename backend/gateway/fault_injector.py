import json
from datetime import datetime, timedelta, timezone
from gateway.models import EvidenceNode, EventLog


VALID_FAULTS = {
    "stale_evidence", "contradictory_observation", "missing_update", "duplicate_action",
    "out_of_order", "race_condition", "partial_failure", "invalid_transition"
}
VALID_SEVERITIES = {"low", "medium", "high", "critical"}


class FaultInjector:
    """Deterministic, reversible prototype fault injection.

    The domain instance used by the prototype is request-scoped. We still take a
    deep snapshot so every mutation can be restored in a finally block.
    Database evidence/event rows are intentionally auditable, while entity state
    itself never leaks into a later simulation.
    """

    def __init__(self, db=None):
        self.db = db

    def validate(self, config):
        if not config:
            return None
        fault_type = str(config.get("type", "")).strip()
        severity = str(config.get("severity", "medium")).lower()
        if fault_type not in VALID_FAULTS:
            raise ValueError(f"Unsupported fault type: {fault_type}")
        if severity not in VALID_SEVERITIES:
            raise ValueError(f"Unsupported fault severity: {severity}")
        params = config.get("params") or {}
        if fault_type == "stale_evidence":
            age = int(params.get("age_seconds", 0))
            if age < 0 or age > 900:
                raise ValueError("stale_evidence age_seconds must be between 0 and 900.")
        return {"type": fault_type, "severity": severity, "params": params}

    def prepare(self, domain, action, payload, entity_id, config):
        config = self.validate(config)
        if not config:
            return payload, None, {}
        fault_type = config["type"]
        params = config["params"]
        context = {}
        if fault_type == "stale_evidence":
            entity = domain.entities.get(entity_id)
            if entity:
                age = int(params.get("age_seconds", 301))
                entity.updated_at = (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()
            context["_fault_stale_evidence"] = True
        elif fault_type == "contradictory_observation":
            field = params.get("field", "price")
            value = params.get("value", 0)
            context["_fault_contradiction"] = True
            context[field] = value
            if self.db is not None:
                self.db.add(EvidenceNode(node_type="fault_observation", entity_id=entity_id,
                                         claim=f"{field}={value}", source="fault-injector",
                                         confidence="1.0", schema_version="1.0"))
                self.db.flush()
        elif fault_type == "missing_update":
            entity = domain.entities.get(entity_id)
            field = params.get("field")
            if entity:
                if not field:
                    field = "quantity_available" if domain.name == "ecommerce" else (
                        "hold_expires_at" if domain.name == "travel" else "linked_pr")
                entity.data.pop(field, None)
                context["_fault_missing_update"] = field
        elif fault_type == "duplicate_action":
            # A pre-existing allowed event with the same payload is the deterministic
            # idempotency signal. It is removed by the request transaction only if
            # the request fails before commit; otherwise it remains auditable.
            if self.db is not None:
                self.db.add(EventLog(domain=domain.name, action=action,
                                     payload_json=json.dumps({k:v for k,v in payload.items() if not k.startswith("_fault_")}, sort_keys=True),
                                     result_json="{}", agent_id=payload.get("_fault_agent_id", "prototype-fault"),
                                     status="allowed", reason="Injected duplicate"))
                self.db.flush()
        elif fault_type == "out_of_order":
            context["_fault_out_of_order"] = True
        elif fault_type == "race_condition":
            context["_fault_race_condition"] = True
        elif fault_type == "partial_failure":
            context["_fault_partial_failure"] = True
        elif fault_type == "invalid_transition":
            entity = domain.entities.get(entity_id)
            if entity:
                entity.state = params.get("forced_state", "sold" if domain.name == "ecommerce" else
                                          "closed" if domain.name == "devops" else "confirmed")
            context["_fault_invalid_transition"] = True
        return {k:v for k,v in payload.items() if not k.startswith("_fault_")}, config, context
