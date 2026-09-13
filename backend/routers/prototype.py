import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import PrototypeRun, ComparisonStat
from benchmark.runner import BenchmarkRunner
from domains.ecommerce import EcommerceDomain
from domains.travel import TravelDomain
from domains.devops import DevOpsDomain
from gateway.interceptor import ToolCallInterceptor
from engine.certificate import CertificateBuilder


DOMAIN_CLASSES = {"ecommerce": EcommerceDomain, "travel": TravelDomain, "devops": DevOpsDomain}
router = APIRouter(prefix="/prototype", tags=["prototype"])


class FaultConfig(BaseModel):
    type: str
    severity: str = "medium"
    params: dict = Field(default_factory=dict)


class SimulateRequest(BaseModel):
    domain: str
    action: str
    payload: dict = Field(default_factory=dict)
    agent_id: str = "prototype-agent"
    fault_config: FaultConfig | None = None
    context_snapshot: dict = Field(default_factory=dict)


class CertificateRequest(BaseModel):
    run_id: str


def _state_machine(domain_name: str):
    domain = DOMAIN_CLASSES[domain_name]()
    transitions = [{
        "from_state": t.from_state, "to_state": t.to_state, "action": t.action,
        "preconditions": t.preconditions, "postconditions": t.postconditions,
        "freshness_ttl_seconds": t.freshness_ttl_seconds
    } for t in domain.transitions]
    facts = [{"name": i.name, "type": i.fact_type} for i in domain.invariants if i.fact_type == "domain_fact"]
    workflow = [{"name": i.name, "type": i.fact_type} for i in domain.invariants if i.fact_type == "workflow_rule"]
    constraints = [{"name": i.name, "type": i.fact_type} for i in domain.invariants if i.fact_type == "user_constraint"]
    return {
        "domain": domain.name, "schema_version": domain.schema_version,
        "entities": list(domain.entities.keys()),
        "states": sorted({e.state for e in domain.entities.values()} | {t.from_state for t in domain.transitions} | {t.to_state for t in domain.transitions}),
        "transitions": transitions,
        "facts": facts, "workflow_rules": workflow, "user_constraints": constraints
    }


def _ensure_comparison_stats(db: Session, domain_name: str):
    rows = db.query(ComparisonStat).filter(ComparisonStat.domain == domain_name).all()
    required = {"agent_alone", "prompt_reflection", "schema_only", "stateless_policy", "tooltruth"}
    if {r.mode for r in rows} >= required:
        return
    # Benchmarks are isolated from the public prototype DB. This prevents
    # benchmark conflict evidence from contaminating a user's live simulation.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database import Base
    from models import Admin, UploadLog, Version, BenchmarkRun, PrototypeRun
    from gateway.models import EventLog, EvidenceNode, EvidenceEdge
    scratch_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=scratch_engine)
    ScratchSession = sessionmaker(bind=scratch_engine, autocommit=False, autoflush=False)
    scratch = ScratchSession()
    try:
        runner = BenchmarkRunner(scratch)
        for mode in ["agent_alone", "prompt_reflection", "schema_only", "stateless_policy", "tooltruth"]:
            result = runner.run(domain_name, mode, persist=False)
            existing = db.query(ComparisonStat).filter(
                ComparisonStat.domain == domain_name, ComparisonStat.mode == mode
            ).first()
            if existing is None:
                db.add(ComparisonStat(
                    domain=domain_name, mode=mode,
                    precision=float(result["precision"]), recall=float(result["recall"]),
                    f1=float(result["f1"]), false_block_rate=float(result["false_block_rate"]),
                    unsafe_prevented=int(result["unsafe_actions_prevented"]),
                    task_success=float(result["task_success_rate"]),
                    avg_latency_ms=float(result["avg_latency_ms"]),
                    token_overhead=int(result["tokens_used"])
                ))
        db.commit()
    finally:
        scratch.close()
        scratch_engine.dispose()


@router.get("/state-machine/{domain}")
def state_machine(domain: str):
    if domain not in DOMAIN_CLASSES:
        raise HTTPException(404, "Unsupported domain")
    return _state_machine(domain)


@router.post("/simulate")
def simulate(body: SimulateRequest, db: Session = Depends(get_db)):
    if body.domain not in DOMAIN_CLASSES:
        raise HTTPException(400, "Unsupported domain")
    if len(body.agent_id) > 120:
        raise HTTPException(400, "agent_id too long")
    if len(json.dumps(body.payload)) > 10000 or len(json.dumps(body.context_snapshot)) > 10000:
        raise HTTPException(400, "Payload too large")
    fault = body.fault_config.model_dump() if body.fault_config else None
    if fault and fault["type"] == "stale_evidence":
        age = int(fault["params"].get("age_seconds", 0))
        if not 0 <= age <= 900:
            raise HTTPException(400, "Stale evidence age must be 0-900 seconds.")

    domain = DOMAIN_CLASSES[body.domain]()
    try:
        out = ToolCallInterceptor(db, domain).call(
            body.domain, body.action, body.payload, body.agent_id,
            body.context_snapshot, fault
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc))

    run_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    summary = {
        **out,
        "run_id": run_id,
        "decision_timestamp": now,
        "domain": body.domain, "action": body.action,
        "entity_id": ToolCallInterceptor.entity_id_for(body.domain, body.action, body.payload),
        "agent_id": body.agent_id,
        "evidence_nodes": out.get("evidence_trail", []),
    }
    row = PrototypeRun(
        run_id=run_id, domain=body.domain, action=body.action, entity_id=summary["entity_id"],
        agent_id=body.agent_id,
        fault_type=(fault or {}).get("type") or out.get("fault_type"),
        fault_severity=(fault or {}).get("severity"),
        decision=out.get("decision", "block" if not out.get("allowed") else "allow"),
        blocked_reason=out.get("reason") if not out.get("allowed") else None,
        summary_json=json.dumps(summary, sort_keys=True),
    )
    db.add(row); db.commit()
    _ensure_comparison_stats(db, body.domain)
    metrics = _comparison_payload(db, body.domain)
    return {**summary, "comparison_metrics": metrics}


@router.post("/certificate")
def certificate(body: CertificateRequest, db: Session = Depends(get_db)):
    row = db.query(PrototypeRun).filter(PrototypeRun.run_id == body.run_id).first()
    if not row:
        raise HTTPException(404, "Prototype run not found")
    if row.certificate_json:
        return json.loads(row.certificate_json)
    cert = CertificateBuilder.build(row)
    row.certificate_json = json.dumps(cert, sort_keys=True)
    db.commit()
    return cert


@router.get("/comparison-metrics")
def comparison_metrics(domain: str | None = None, db: Session = Depends(get_db)):
    if domain is not None and domain not in DOMAIN_CLASSES:
        raise HTTPException(400, "Unsupported domain")
    if domain:
        _ensure_comparison_stats(db, domain)
        return _comparison_payload(db, domain)
    domains = {}
    for name in DOMAIN_CLASSES:
        _ensure_comparison_stats(db, name)
        domains[name] = _comparison_payload(db, name)
    return domains


def _comparison_payload(db, domain):
    rows = db.query(ComparisonStat).filter(ComparisonStat.domain == domain).order_by(ComparisonStat.id.asc()).all()
    modes = ["agent_alone", "prompt_reflection", "schema_only", "stateless_policy", "tooltruth"]
    return [{
        "mode": r.mode, "detection_precision": r.precision, "detection_recall": r.recall,
        "f1": r.f1, "false_block_rate": r.false_block_rate,
        "unsafe_actions_prevented": r.unsafe_prevented, "task_success": r.task_success,
        "avg_latency_ms": r.avg_latency_ms, "token_overhead": r.token_overhead
    } for mode in modes for r in rows if r.mode == mode]
