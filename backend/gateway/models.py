
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from database import Base
class EventLog(Base):
    __tablename__="event_logs"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    domain: Mapped[str]=mapped_column(String(40),index=True)
    action: Mapped[str]=mapped_column(String(80))
    payload_json: Mapped[str]=mapped_column(Text)
    result_json: Mapped[str]=mapped_column(Text)
    timestamp: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))
    agent_id: Mapped[str]=mapped_column(String(120),default="anonymous")
    status: Mapped[str]=mapped_column(String(20),default="allowed")
    reason: Mapped[str]=mapped_column(Text,default="")
    dependencies_json: Mapped[str]=mapped_column(Text,default="[]")
class EvidenceNode(Base):
    __tablename__="evidence_nodes"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    node_type: Mapped[str]=mapped_column(String(40))
    entity_id: Mapped[str]=mapped_column(String(120),index=True)
    claim: Mapped[str]=mapped_column(Text)
    source: Mapped[str]=mapped_column(String(255))
    confidence: Mapped[str]=mapped_column(String(30),default="1.0")
    timestamp: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))
    schema_version: Mapped[str]=mapped_column(String(30),default="1.0")
    # --- added for real (non-simulator) providers; all optional for old rows ---
    provider: Mapped[str]=mapped_column(String(40),default="simulator",server_default="simulator")
    resource_id: Mapped[str|None]=mapped_column(String(255),nullable=True)       # e.g. Shopify inventory item id
    location_id: Mapped[str|None]=mapped_column(String(255),nullable=True)       # e.g. Shopify location id
    source_updated_at: Mapped[datetime|None]=mapped_column(DateTime,nullable=True)  # when the SOURCE says it changed
    fetched_at: Mapped[datetime|None]=mapped_column(DateTime,nullable=True)          # when ToolTruth looked
class EvidenceEdge(Base):
    __tablename__="evidence_edges"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    from_node_id: Mapped[int]=mapped_column(ForeignKey("evidence_nodes.id"))
    to_node_id: Mapped[int]=mapped_column(ForeignKey("evidence_nodes.id"))
    relation_type: Mapped[str]=mapped_column(String(60))
class ShopifyWebhookEvent(Base):
    """One row per Shopify webhook delivery. event_id is unique, so repeats are detected."""
    __tablename__="shopify_webhook_events"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    event_id: Mapped[str]=mapped_column(String(120),unique=True,index=True)
    topic: Mapped[str]=mapped_column(String(80))
    shop_domain: Mapped[str]=mapped_column(String(255),default="")
    inventory_item_id: Mapped[str]=mapped_column(String(40),index=True)
    location_id: Mapped[str]=mapped_column(String(40))
    available: Mapped[int|None]=mapped_column(Integer,nullable=True)
    triggered_at: Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    source_updated_at: Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    received_at: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc).replace(tzinfo=None))
    status: Mapped[str]=mapped_column(String(20),default="processed")  # processed | stale_ignored
    entity_id: Mapped[str|None]=mapped_column(String(120),nullable=True)

class OrderAttempt(Base):
    """One customer order attempt, from verification to (optional) Shopify execution.
    idempotency_key is unique, so a repeated request can never create a second order."""
    __tablename__="order_attempts"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    run_id: Mapped[str]=mapped_column(String(64),unique=True,index=True)
    idempotency_key: Mapped[str]=mapped_column(String(80),unique=True,index=True)
    request_hash: Mapped[str]=mapped_column(String(64))
    # verifying | executing | rejected | needs_evidence | verified_not_executed |
    # executed_verified | executed_unverified | execution_failed | uncertain
    status: Mapped[str]=mapped_column(String(30),index=True,default="verifying")
    decision: Mapped[str|None]=mapped_column(String(30),nullable=True)
    reason: Mapped[str]=mapped_column(Text,default="")
    shopify_tag: Mapped[str]=mapped_column(String(60),default="")
    order_mode: Mapped[str]=mapped_column(String(20),default="complete")
    cart_json: Mapped[str]=mapped_column(Text,default="[]")
    customer_json: Mapped[str]=mapped_column(Text,default="{}")
    checks_json: Mapped[str]=mapped_column(Text,default="[]")
    lines_json: Mapped[str]=mapped_column(Text,default="[]")
    evidence_json: Mapped[str]=mapped_column(Text,default="[]")
    execution_json: Mapped[str]=mapped_column(Text,default="{}")
    shopify_order_id: Mapped[str|None]=mapped_column(String(120),nullable=True)
    shopify_order_name: Mapped[str|None]=mapped_column(String(60),nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc).replace(tzinfo=None))
