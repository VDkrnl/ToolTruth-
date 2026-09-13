import json, time, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlalchemy.orm import Session
from gateway.interceptor import ToolCallInterceptor, DOMAINS
from gateway.models import EvidenceNode
from models import BenchmarkRun
from domains.ecommerce import EcommerceDomain
from domains.devops import DevOpsDomain
from domains.travel import TravelDomain

DOMAIN_CLASSES = {"ecommerce": EcommerceDomain, "devops": DevOpsDomain, "travel": TravelDomain}


class BenchmarkRunner:
    def __init__(self, db: Session): self.db = db

    def _prepare_fault(self, domain, task):
        fault = task.get("fault_type")
        setup = task.get("setup_state") or {}
        domain.reset(); domain.apply_setup_state(setup)
        entity_id = self._entity_id(task["domain"], task["tool_call"]["action"], task["tool_call"]["payload"])
        self.db.query(EvidenceNode).filter(EvidenceNode.entity_id == entity_id, EvidenceNode.source == "benchmark").delete(synchronize_session=False)
        self.db.commit()
        payload = dict(task["tool_call"]["payload"])
        if fault == "stale_fact":
            entity_id = self._entity_id(task["domain"], task["tool_call"]["action"], payload)
            entity = domain.entities.get(entity_id)
            if entity:
                entity.updated_at = (datetime.now(timezone.utc) - timedelta(seconds=301)).isoformat()
        if fault == "contradiction":
            entity_id = self._entity_id(task["domain"], task["tool_call"]["action"], payload)
            conflict = task.get("conflict_claim") or {"field": "price", "value": -1}
            self.db.add(EvidenceNode(node_type="benchmark_conflict", entity_id=entity_id,
                                     claim=f"{conflict['field']}={conflict['value']}", source="benchmark",
                                     confidence="1.0", schema_version="1.0")); self.db.commit()
        return payload

    @staticmethod
    def _entity_id(domain, action, payload):
        return ToolCallInterceptor.entity_id_for(domain, action, payload)

    def _schema_valid(self, domain, action, payload):
        from engine.consistency import ConsistencyEngine
        return ConsistencyEngine().check_schema(domain, action, payload).passed

    def run(self, domain_name, mode="tooltruth", persist=True):
        path = Path(__file__).parent / "tasks" / f"{domain_name}.json"
        tasks = json.loads(path.read_text())
        run_id = uuid.uuid4().hex
        results=[]; correct=0; blocked=0; unsafe_prevented=0; allowed_expected=sum(t["expected_outcome"]=="allowed" for t in tasks)
        for task in tasks:
            action=task["tool_call"]["action"]
            agent_id=f"benchmark-{run_id[:8]}-{task['id']}"
            start=time.perf_counter()
            d=DOMAIN_CLASSES[domain_name](); payload=self._prepare_fault(d,task)
            if mode == "tooltruth":
                interceptor=ToolCallInterceptor(self.db, d)
                if task.get("fault_type") == "duplicate_action":
                    interceptor.call(domain_name, action, payload, agent_id)
                result=interceptor.call(domain_name, action, payload, agent_id, task.get("context_snapshot") or {})
            else:
                sim=d.simulate_tool_call(action,payload)
                schema_ok=self._schema_valid(domain_name,action,payload)
                if mode == "agent_alone":
                    allowed=sim.success
                    checks=[]
                elif mode == "schema_only":
                    allowed=schema_ok
                    checks=[{"name":"schema","passed":schema_ok}]
                elif mode == "prompt_reflection":
                    hard_invariant_errors={"insufficient_stock","not_in_stock","blocking_issue","staging_required","missing_linked_pr","seat_unavailable","hold_expired","seat_not_held","illegal_state"}
                    allowed=schema_ok and sim.success and not (sim.data.get("error") in hard_invariant_errors)
                    checks=[{"name":"schema","passed":schema_ok},{"name":"simulator","passed":sim.success}]
                elif mode == "stateless_policy":
                    # A policy-only baseline sees the current simulator result and
                    # action legality, but has no historical evidence, freshness,
                    # ordering, or idempotency state.
                    hard_policy_errors={"insufficient_stock","not_in_stock","blocking_issue","staging_required",
                                        "missing_linked_pr","seat_unavailable","hold_expired","seat_not_held",
                                        "illegal_state","product_not_found","seat_not_found","booking_not_found",
                                        "issue_not_found","deployment_not_found"}
                    allowed=schema_ok and sim.success and sim.data.get("error") not in hard_policy_errors
                    checks=[{"name":"schema","passed":schema_ok},{"name":"policy","passed":allowed}]
                else: raise ValueError(f"Unsupported mode: {mode}")
                result={"allowed":allowed,"result":sim.data,"reason":f"{mode} baseline","fault_type":task.get("fault_type"),"evidence_trail":[],"checks":checks}
            latency=(time.perf_counter()-start)*1000
            expected=task["expected_outcome"]; outcome="allowed" if result["allowed"] else "blocked"; ok=outcome==expected
            correct+=int(ok); blocked+=int(not result["allowed"])
            if expected=="blocked" and not result["allowed"]: unsafe_prevented+=1
            results.append({"task_id":task["id"],"outcome":outcome,"expected":expected,"correct":ok,
                            "fault_type":result.get("fault_type"),"expected_fault":task.get("expected_fault"),
                            "latency_ms":round(latency,3),"tokens_used":0,"reason":result.get("reason")})
        total=len(results); expected_blocked=total-allowed_expected
        precision=unsafe_prevented/max(blocked,1); recall=unsafe_prevented/max(expected_blocked,1)
        f1=(2*precision*recall/(precision+recall)) if precision+recall else 0
        false_blocks=max(blocked-unsafe_prevented,0)
        summary={"domain":domain_name,"mode":mode,"total_tasks":total,"correct":correct,
                 "precision":round(precision,3),"recall":round(recall,3),"f1":round(f1,3),
                 "false_block_rate":round(false_blocks/max(allowed_expected,1),3),
                 "unsafe_actions_prevented":unsafe_prevented,"task_success_rate":round(correct/total,3),
                 "avg_latency_ms":round(sum(r["latency_ms"] for r in results)/total,3),"tokens_used":0}
        if persist:
            self.db.add(BenchmarkRun(run_id=run_id,domain=domain_name,mode=mode,results_json=json.dumps(results),summary_json=json.dumps(summary)))
            self.db.commit()
        return {"run_id":run_id,**summary,"results":results}
