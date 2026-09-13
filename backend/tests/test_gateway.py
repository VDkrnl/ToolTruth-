from database import SessionLocal, init_db
from gateway.interceptor import ToolCallInterceptor
from benchmark.runner import BenchmarkRunner
from gateway.models import EvidenceNode, EventLog


def test_gateway_call():
    init_db(); db=SessionLocal()
    try:
        db.query(EvidenceNode).filter(EvidenceNode.source=="benchmark").delete(synchronize_session=False); db.commit()
        out=ToolCallInterceptor(db).call("ecommerce","get_inventory",{"product_id":"SKU-100"},agent_id="gateway-basic-unique")
        assert out["allowed"] is True and out["evidence_trail"]
    finally: db.close()


def test_gateway_blocks_duplicate():
    init_db(); db=SessionLocal()
    try:
        db.query(EvidenceNode).filter(EvidenceNode.source=="benchmark").delete(synchronize_session=False); db.commit()
        i=ToolCallInterceptor(db)
        agent="gateway-dup-unique"
        assert i.call("ecommerce","get_inventory",{"product_id":"SKU-100"},agent)["allowed"]
        second=i.call("ecommerce","get_inventory",{"product_id":"SKU-100"},agent)
        assert second["allowed"] is False and second["fault_type"]=="duplicate_action"
    finally: db.close()


def test_gateway_evidence_edges():
    init_db(); db=SessionLocal()
    try:
        i=ToolCallInterceptor(db)
        i.call("ecommerce","get_inventory",{"product_id":"SKU-100"},agent_id="edge-a")
        i.call("ecommerce","get_inventory",{"product_id":"SKU-101"},agent_id="edge-b")
        # Same entity, different agent: evidence should link the nodes.
        i.call("ecommerce","get_inventory",{"product_id":"SKU-100"},agent_id="edge-c")
        from gateway.models import EvidenceNode, EvidenceEdge
        node_ids=[n.id for n in db.query(EvidenceNode).filter_by(entity_id="SKU-100").all()]
        assert db.query(EvidenceEdge).filter(EvidenceEdge.to_node_id.in_(node_ids)).count() > 0
    finally: db.close()


def test_benchmark_runner_tooltruth():
    init_db(); db=SessionLocal()
    try:
        r=BenchmarkRunner(db).run("ecommerce","tooltruth")
        assert r["task_success_rate"] > 0.8
    finally: db.close()


def test_benchmark_baselines_differ():
    init_db(); db=SessionLocal()
    try:
        a=BenchmarkRunner(db).run("ecommerce","tooltruth")
        b=BenchmarkRunner(db).run("ecommerce","agent_alone")
        assert a["f1"] != b["f1"]
    finally: db.close()
