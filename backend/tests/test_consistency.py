from datetime import datetime, timezone
from engine.consistency import ConsistencyEngine
from domains.ecommerce import EcommerceDomain
from gateway.models import EventLog, EvidenceNode
from database import SessionLocal, init_db


def test_stale_fault():
    r = ConsistencyEngine().run_all(EcommerceDomain(), "get_inventory", {"product_id":"SKU-100"}, {"as_of_timestamp":"2020-01-01T00:00:00+00:00"})
    assert not r.passed and r.fault_type == "stale_fact"


def test_schema():
    r = ConsistencyEngine().check_schema("ecommerce", "reserve", {})
    assert not r.passed


def test_duplicate_action_detected():
    init_db(); db=SessionLocal()
    try:
        db.add(EventLog(domain="ecommerce", action="get_inventory", payload_json='{"product_id":"SKU-100"}', result_json='{}', agent_id="dup-test")); db.commit()
        r=ConsistencyEngine(db).check_duplicate("dup-test","ecommerce","get_inventory","SKU-100")
        assert not r.passed
    finally: db.close()


def test_contradiction_detected():
    init_db(); db=SessionLocal()
    try:
        db.add(EvidenceNode(node_type="benchmark_conflict", entity_id="SKU-100", claim="price=888", source="benchmark")); db.commit()
        r=ConsistencyEngine(db).run_all(EcommerceDomain(), "get_inventory", {"product_id":"SKU-100"}, {"price":999,"as_of_timestamp":datetime.now(timezone.utc).isoformat()}, historical_claims=[{"field":"price","value":888,"source":"benchmark"}], entity_id="SKU-100", agent_id="unique-contradiction")
        assert not r.passed and r.fault_type == "contradiction"
    finally: db.close()


def test_invariant_violation():
    d=EcommerceDomain(); d.entities["SKU-100"].data["quantity_available"]=-1
    r=ConsistencyEngine().run_all(d,"get_inventory",{"product_id":"SKU-100"},{"quantity_available":-1,"as_of_timestamp":datetime.now(timezone.utc).isoformat()})
    assert not r.passed and r.fault_type == "invariant_violation"
