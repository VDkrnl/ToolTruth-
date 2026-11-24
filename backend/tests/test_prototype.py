import json
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from database import Base
from models import PrototypeRun
from gateway.models import EventLog, EvidenceNode
from gateway.interceptor import ToolCallInterceptor
from domains.ecommerce import EcommerceDomain
from routers.prototype import _state_machine
from main import app
import pytest


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

from engine.certificate import CertificateBuilder


def test_state_machine_schema_all_domains():
    for domain in ("ecommerce", "travel", "devops"):
        body = _state_machine(domain)
        assert body["schema_version"] == "1.0"
        assert body["entities"]
        assert body["states"]
        assert body["transitions"]
        assert all("preconditions" in t and "postconditions" in t and "freshness_ttl_seconds" in t
                   for t in body["transitions"])


def test_simulate_allow(client):
    r = client.post("/prototype/simulate", json={
        "domain":"ecommerce","action":"get_inventory",
        "payload":{"product_id":"SKU-100"},"agent_id":"prototype-test"
    })
    assert r.status_code == 200
    assert r.json()["decision"] == "allow"


def test_simulate_invalid_transition_blocks(client):
    r = client.post("/prototype/simulate", json={
        "domain":"ecommerce","action":"get_inventory",
        "payload":{"product_id":"SKU-100"},"agent_id":"invalid-test",
        "fault_config":{"type":"invalid_transition","severity":"high","params":{}}
    })
    assert r.status_code == 200
    assert r.json()["decision"] == "block"


def test_simulate_stale_evidence_requests_more_evidence(client):
    r = client.post("/prototype/simulate", json={
        "domain":"ecommerce","action":"get_inventory",
        "payload":{"product_id":"SKU-100"},"agent_id":"stale-test",
        "fault_config":{"type":"stale_evidence","severity":"medium","params":{"age_seconds":400}}
    })
    assert r.status_code == 200
    body=r.json()
    assert body["decision"] == "request_more_evidence"
    assert any(c["name"]=="freshness" and not c["passed"] for c in body["checks"])


def test_user_constraint_is_not_hard_block(client):
    r = client.post("/prototype/simulate", json={
        "domain":"ecommerce","action":"reserve",
        "payload":{"product_id":"SKU-100","quantity":1},
        "context_snapshot":{"budget_limit":500},"agent_id":"budget-test"
    })
    assert r.status_code == 200
    assert r.json()["decision"] == "request_more_evidence"


def test_certificate_fingerprint_reproducible(client):
    r = client.post("/prototype/simulate", json={
        "domain":"ecommerce","action":"get_inventory",
        "payload":{"product_id":"SKU-100"},"agent_id":"cert-test"
    })
    run_id=r.json()["run_id"]
    a=client.post("/prototype/certificate",json={"run_id":run_id}).json()
    b=client.post("/prototype/certificate",json={"run_id":run_id}).json()
    assert a["sha256_fingerprint"] == b["sha256_fingerprint"]
    assert len(a["sha256_fingerprint"]) == 64


def test_comparison_metrics_have_five_numeric_modes(client):
    r=client.get("/prototype/comparison-metrics?domain=ecommerce")
    assert r.status_code == 200
    rows=r.json()
    assert [x["mode"] for x in rows] == ["agent_alone","prompt_reflection","schema_only","stateless_policy","tooltruth"]
    for row in rows:
        for key in ("detection_precision","detection_recall","f1","false_block_rate","task_success"):
            assert 0 <= float(row[key]) <= 1


def test_fault_reversibility():
    engine=create_engine("sqlite:///:memory:",connect_args={"check_same_thread":False})
    Base.metadata.create_all(bind=engine)
    Session=sessionmaker(bind=engine)
    db=Session()
    try:
        domain=EcommerceDomain()
        before=domain.snapshot()
        ToolCallInterceptor(db,domain).call(
            "ecommerce","get_inventory",{"product_id":"SKU-100"},
            agent_id="reversible",
            fault_config={"type":"invalid_transition","severity":"high","params":{}}
        )
        assert domain.snapshot() == before
    finally:
        db.close(); engine.dispose()

def test_duplicate_fault_blocks(client):
    r=client.post("/prototype/simulate",json={
        "domain":"ecommerce","action":"get_inventory",
        "payload":{"product_id":"SKU-100"},"agent_id":"duplicate-test",
        "fault_config":{"type":"duplicate_action","severity":"high","params":{}}
    })
    assert r.status_code == 200
    assert r.json()["decision"] == "block"
    assert r.json()["fault_type"] == "duplicate_action"
