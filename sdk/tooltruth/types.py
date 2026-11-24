from pydantic import BaseModel
from typing import Any, Optional


class GatewayResponse(BaseModel):
    allowed: bool
    # B-27: add decision field (allow / block / request_more_evidence)
    decision: Optional[str] = None
    result: dict[str, Any]
    reason: str
    fault_type: Optional[str] = None
    evidence_trail: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []


class EvidenceGraph(BaseModel):
    entity_id: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
