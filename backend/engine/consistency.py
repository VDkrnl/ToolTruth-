import json
from datetime import datetime, timedelta, timezone
from typing import Literal
from .schemas import ConsistencyReport, CheckResult


class ConsistencyEngine:
    def __init__(self, db=None, duplicate_window_seconds=60):
        self.db = db
        self.duplicate_window_seconds = duplicate_window_seconds

    def check_schema(self, domain, action, payload):
        required = {
            "ecommerce": {
                "reserve": ["product_id", "quantity"], "sell": ["product_id"], "return": ["product_id"],
                "get_inventory": ["product_id"],
            },
            "devops": {
                "deploy": ["environment"], "get_issue": ["issue_id"], "start": ["issue_id"],
                "close_issue": ["issue_id"], "review": ["issue_id"], "merge": ["issue_id"], "reopen": ["issue_id"],
            },
            "travel": {
                "hold": ["seat_id"], "confirm": ["booking_id"], "get_availability": ["seat_id"],
                "cancel": ["booking_id"], "check_in": ["booking_id"], "board": ["booking_id"],
            },
        }.get(domain, {})
        if action not in required:
            return CheckResult(name="schema", passed=False, reason=f"Unknown action '{action}' for {domain}.")
        missing = [k for k in required[action] if k not in payload]
        if missing:
            return CheckResult(name="schema", passed=False, reason=f"Missing fields: {', '.join(missing)}.")
        if domain == "ecommerce" and action == "reserve":
            quantity = payload.get("quantity")
            if not isinstance(quantity, (int, float)) or isinstance(quantity, bool) or quantity <= 0:
                return CheckResult(name="schema", passed=False, reason=f"quantity must be > 0 for reserve, got {quantity}.")
        return CheckResult(name="schema", passed=True, reason="Schema valid.")

    def check_state(self, domain, entity_state, target_state, action):
        transition = domain.transition_for(action, entity_state)
        if transition is None:
            if any(t.action == action for t in domain.transitions):
                return CheckResult(name="state_transition", passed=False,
                                   reason=f"No legal transition from {entity_state} for {action}.")
            return CheckResult(name="state_transition", passed=True, reason="No state transition required.")
        ok = domain.allowed_transition(entity_state, target_state, action)
        return CheckResult(name="state_transition", passed=ok,
                           reason="Legal state transition." if ok else
                           f"Illegal transition {entity_state} -> {target_state} for {action}.")

    def check_staleness(self, timestamp, max_age_seconds=300):
        try:
            parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
            age = max(0, (datetime.now(timezone.utc) - parsed).total_seconds())
            ok = age <= max_age_seconds
            return CheckResult(name="freshness", passed=ok,
                               reason="Fresh enough." if ok else f"Fact is {int(age)}s old; limit is {max_age_seconds}s.")
        except Exception:
            return CheckResult(name="freshness", passed=False, reason="Invalid timestamp.")

    def check_contradictions(self, context, new_claims):
        context = context or {}
        conflicts = [f"{c['field']} changed from {context[c['field']]} to {c['value']}"
                     for c in new_claims if c.get("field") in context and context[c["field"]] != c["value"]]
        return CheckResult(name="contradiction", passed=not conflicts,
                           reason="No contradiction detected." if not conflicts else "; ".join(conflicts))

    def check_historical_contradictions(self, historical_claims, new_claims):
        prior = {c.get("field"): c.get("value") for c in historical_claims
                 if c.get("field") and c.get("source") not in {"simulator", "prototype"}}
        conflicts = [f"{c['field']} changed from {prior[c['field']]} to {c['value']}"
                     for c in new_claims if c.get("field") in prior and prior[c['field']] != c["value"]]
        return CheckResult(name="contradiction", passed=not conflicts,
                           reason="No historical contradiction detected." if not conflicts else "; ".join(conflicts))

    def check_invariants(self, domain, context):
        failures = [reason for inv in domain.invariants
                    if inv.fact_type != "user_constraint"
                    for ok, reason in [inv.check(context)] if not ok]
        return CheckResult(name="invariants", passed=not failures,
                           reason="All domain facts and workflow rules hold." if not failures else "; ".join(failures))

    def check_user_constraints(self, domain, action, payload, agent_context=None):
        context = {**(agent_context or {}), **payload}
        # Add the observed price for e-commerce/travel when it is available in context.
        if "price" not in context and context.get("observed_price") is not None:
            context["price"] = context["observed_price"]
        failures = []
        for inv in domain.invariants:
            if inv.fact_type == "user_constraint":
                ok, reason = inv.check(context)
                if not ok:
                    failures.append(reason)
        return CheckResult(name="user_constraints", passed=not failures,
                           reason="User constraints satisfied." if not failures else "; ".join(failures))

    def check_temporal_failures(self, domain, entity, action, payload=None, historical_claims=None):
        checks = []
        payload = payload or {}
        historical_claims = historical_claims or []
        # Snapshot-based inventory drift: caller supplies pre_reservation_quantity when known.
        if domain.name == "ecommerce" and action in {"sell", "reserve"}:
            old = payload.get("pre_reservation_quantity")
            current = entity.data.get("quantity_available") if entity else None
            if old is not None and current is not None and action == "sell" and current != old:
                checks.append(CheckResult(name="temporal_inventory", passed=False,
                                          reason=f"Inventory changed from {old} to {current} after reservation."))
        if domain.name == "travel" and action == "cancel":
            expiry = payload.get("hold_expires_at")
            cancelled_at = payload.get("event_timestamp")
            if expiry and cancelled_at:
                try:
                    exp = datetime.fromisoformat(expiry.replace("Z","+00:00"))
                    at = datetime.fromisoformat(cancelled_at.replace("Z","+00:00"))
                    if exp.tzinfo is None: exp=exp.replace(tzinfo=timezone.utc)
                    if at.tzinfo is None: at=at.replace(tzinfo=timezone.utc)
                    if at > exp:
                        checks.append(CheckResult(name="temporal_cancellation", passed=False,
                                                  reason="Cancellation occurred after the hold expiry."))
                except ValueError:
                    pass
        if payload.get("compensation_marker"):
            checks.append(CheckResult(name="retry_after_compensation", passed=False,
                                      reason="A retry was attempted after compensation was recorded."))
        return checks

    def check_ordering(self, events, entity_id):
        relevant = [e for e in events if e is not None]
        relevant.sort(key=lambda e: e.timestamp or datetime.min.replace(tzinfo=timezone.utc))
        last = None
        for event in relevant:
            deps = []
            try: deps = json.loads(getattr(event, "dependencies_json", "[]") or "[]")
            except Exception: deps = []
            if last is not None and deps and last.id not in deps:
                return CheckResult(name="ordering", passed=False,
                                   reason=f"Event {event.id} violates its declared causal dependency.")
            last = event
        return CheckResult(name="ordering", passed=True, reason="Event ordering is causally consistent.")

    def check_idempotency(self, agent_id, domain, action, entity_id, payload_hash, window_seconds=None):
        if self.db is None or not entity_id:
            return CheckResult(name="idempotency", passed=True, reason="Duplicate history unavailable.")
        from gateway.models import EventLog
        from datetime import timedelta
        import hashlib
        window = self.duplicate_window_seconds if window_seconds is None else window_seconds
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window)
        events = self.db.query(EventLog).filter(
            EventLog.agent_id == agent_id, EventLog.domain == domain,
            EventLog.action == action, EventLog.status == "allowed"
        ).order_by(EventLog.id.desc()).all()
        for event in events:
            event_time = event.timestamp
            if event_time is None: continue
            if event_time.tzinfo is None: event_time=event_time.replace(tzinfo=timezone.utc)
            if event_time < cutoff: continue
            try: old_payload=json.loads(event.payload_json or "{}")
            except Exception: old_payload={}
            old_hash=hashlib.sha256(json.dumps(old_payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
            event_entity_id=(old_payload.get("product_id") or old_payload.get("issue_id") or
                             old_payload.get("deployment_id") or old_payload.get("seat_id") or
                             old_payload.get("booking_id") or old_payload.get("entity_id"))
            if event_entity_id == entity_id and old_hash == payload_hash:
                return CheckResult(name="idempotency", passed=False,
                                   reason=f"Duplicate identical payload for {entity_id} within {window}s.")
        return CheckResult(name="idempotency", passed=True, reason="No identical retry in the idempotency window.")

    # Backward-compatible alias retained for the existing gateway/tests.
    def check_duplicate(self, agent_id, domain, action, entity_id, window_seconds=None):
        import hashlib
        return self.check_idempotency(agent_id, domain, action, entity_id,
                                      hashlib.sha256(b"{}").hexdigest(), window_seconds) if self.db is None else self._legacy_duplicate(agent_id, domain, action, entity_id, window_seconds)

    def _legacy_duplicate(self, agent_id, domain, action, entity_id, window_seconds=None):
        from gateway.models import EventLog
        from datetime import timedelta
        window = self.duplicate_window_seconds if window_seconds is None else window_seconds
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window)
        for event in self.db.query(EventLog).filter(EventLog.agent_id==agent_id, EventLog.domain==domain,
                                                    EventLog.action==action, EventLog.status=="allowed").order_by(EventLog.id.desc()).all():
            event_time=event.timestamp
            if event_time is None: continue
            if event_time.tzinfo is None: event_time=event_time.replace(tzinfo=timezone.utc)
            if event_time < cutoff: continue
            try: p=json.loads(event.payload_json or "{}")
            except Exception: p={}
            eid=(p.get("product_id") or p.get("issue_id") or p.get("deployment_id") or p.get("seat_id") or p.get("booking_id") or p.get("entity_id"))
            if eid == entity_id:
                return CheckResult(name="duplicate_action", passed=False,
                                   reason=f"Duplicate {action} for {entity_id} by agent {agent_id} within {window}s.")
        return CheckResult(name="duplicate_action", passed=True, reason="No duplicate action in the configured window.")

    @staticmethod
    def produce_decision(checks: list[CheckResult]) -> Literal["allow","block","request_more_evidence"]:
        hard_names={"schema","state_transition","invariants","contradiction","ordering","idempotency",
                    "duplicate_action","tool_result","temporal_inventory","temporal_cancellation",
                    "retry_after_compensation"}
        if any((not c.passed and c.name in hard_names) for c in checks):
            return "block"
        if any(not c.passed and c.name in {"user_constraints","freshness"} for c in checks):
            return "request_more_evidence"
        if any(not c.passed for c in checks):
            return "block"
        return "allow"

    def run_all(self, domain, action, payload, tool_data, context=None,
                entity_id=None, agent_id="anonymous", entity_state=None,
                target_state=None, historical_claims=None, source_timestamp=None):
        context=context or {}
        checks=[self.check_schema(domain.name,action,payload)]
        transition=domain.transition_for(action, entity_state)
        ttl=transition.freshness_ttl_seconds if transition else int(payload.get("max_age_seconds",300))
        ts=source_timestamp or tool_data.get("as_of_timestamp")
        if ts: checks.append(self.check_staleness(ts, int(payload.get("max_age_seconds",ttl))))
        checks.append(self.check_state(domain,entity_state,target_state,action))
        historical_claims=historical_claims or []
        new_claims=[{"field":k,"value":v} for k,v in tool_data.items()
                    if k not in {"error","as_of_timestamp","_source_timestamp"} and isinstance(v,(str,int,float,bool))]
        if historical_claims or context:
            checks.append(self.check_historical_contradictions(historical_claims,new_claims))
            checks.append(self.check_contradictions(context,new_claims))
        if entity_id:
            import hashlib
            payload_hash=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
            checks.append(self.check_idempotency(agent_id,domain.name,action,entity_id,payload_hash))
        if tool_data.get("error"):
            checks.append(CheckResult(name="tool_result",passed=False,
                                      reason=f"Simulator rejected the action: {tool_data['error']}."))
        checks.append(self.check_invariants(domain,{**tool_data,**payload}))
        entity_for_constraints = domain.entities.get(entity_id) if entity_id else None
        constraint_context = {**(entity_for_constraints.data if entity_for_constraints else {}), **context, **payload, **tool_data}
        checks.append(self.check_user_constraints(domain,action,constraint_context,context))
        checks.extend(self.check_temporal_failures(domain,
                        domain.entities.get(entity_id) if entity_id else None, action,payload,historical_claims))
        decision=self.produce_decision(checks)
        failed=[c for c in checks if not c.passed]
        fault=None
        if failed:
            names={c.name for c in failed}
            if "idempotency" in names or "duplicate_action" in names: fault="duplicate_action"
            elif "freshness" in names: fault="stale_fact"
            elif "contradiction" in names: fault="contradiction"
            elif "state_transition" in names: fault="illegal_transition"
            elif "user_constraints" in names: fault="user_constraint"
            elif "invariants" in names: fault="invariant_violation"
            elif "tool_result" in names: fault=tool_data.get("error","tool_error")
            else: fault=failed[0].name
        return ConsistencyReport(passed=(decision=="allow"), decision=decision, checks=checks,
                                 fault_type=fault, blocked_reason=(failed[0].reason if failed else None))
