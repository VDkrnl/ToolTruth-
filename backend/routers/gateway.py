import json
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
from auth import current_admin, optional_admin
from gateway.interceptor import ToolCallInterceptor
from gateway.models import EventLog, EvidenceNode, EvidenceEdge
from pydantic import BaseModel, Field


class GatewayCall(BaseModel):
    domain: str
    action: str
    payload: dict = Field(default_factory=dict)
    agent_id: str = "demo-agent"
    context_snapshot: dict = Field(default_factory=dict)


router = APIRouter(prefix="/gateway", tags=["gateway"])
KNOWN_DOMAINS = {"ecommerce", "devops", "travel"}


@router.post("/call")
def call(body: GatewayCall, db: Session = Depends(get_db)):
    # /gateway/call backs the site's live demo. Restrict to simulator domains and
    # cap free-form field sizes to limit blast radius of anonymous callers.
    if body.domain not in KNOWN_DOMAINS:
        raise HTTPException(400, f"Unsupported domain: {body.domain}")
    if len(body.agent_id) > 120:
        raise HTTPException(400, "agent_id too long")
    if len(json.dumps(body.payload)) > 10_000 or len(json.dumps(body.context_snapshot)) > 10_000:
        raise HTTPException(400, "payload too large")
    try:
        return ToolCallInterceptor(db).call(
            body.domain, body.action, body.payload, body.agent_id, body.context_snapshot)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/events")
def events(limit: int = 50, db: Session = Depends(get_db), _=Depends(current_admin)):
    rows = db.query(EventLog).order_by(EventLog.id.desc()).limit(min(limit, 200)).all()
    return [{"id": r.id, "domain": r.domain, "action": r.action, "status": r.status,
             "reason": r.reason, "agent_id": r.agent_id,
             "timestamp": r.timestamp.isoformat()} for r in rows]


@router.get("/evidence/{entity_id:path}")
def evidence(entity_id: str, db: Session = Depends(get_db),
             admin=Depends(optional_admin)):
    # Shopify-sourced evidence contains internal order identifiers and stock data
    # that should not be public. Simulator (demo) evidence remains public.
    if entity_id.startswith("shopify") and admin is None:
        raise HTTPException(401, "Authentication required for Shopify evidence.")
    rows = (db.query(EvidenceNode)
            .filter(EvidenceNode.entity_id == entity_id)
            .order_by(EvidenceNode.id.asc()).all())
    node_ids = [r.id for r in rows]
    edges = (db.query(EvidenceEdge)
             .filter(EvidenceEdge.from_node_id.in_(node_ids),
                     EvidenceEdge.to_node_id.in_(node_ids)).all()
             if node_ids else [])
    return {
        "entity_id": entity_id,
        "nodes": [{"id": r.id, "node_type": r.node_type, "claim": r.claim,
                   "source": r.source, "confidence": r.confidence,
                   "timestamp": r.timestamp.isoformat(),
                   "schema_version": r.schema_version} for r in rows],
        "edges": [{"id": e.id, "from_node_id": e.from_node_id,
                   "to_node_id": e.to_node_id, "relation_type": e.relation_type}
                  for e in edges],
    }
