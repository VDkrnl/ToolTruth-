
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
class EvidenceEdge(Base):
    __tablename__="evidence_edges"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    from_node_id: Mapped[int]=mapped_column(ForeignKey("evidence_nodes.id"))
    to_node_id: Mapped[int]=mapped_column(ForeignKey("evidence_nodes.id"))
    relation_type: Mapped[str]=mapped_column(String(60))
