from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, DateTime, Text, ForeignKey, Float
from sqlalchemy.orm import Mapped, mapped_column
from database import Base

class Admin(Base):
    __tablename__="admins"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    username: Mapped[str]=mapped_column(String(80),unique=True,index=True)
    password_hash: Mapped[str]=mapped_column(String(255))
    created_at: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))

class UploadLog(Base):
    __tablename__="upload_log"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    filename: Mapped[str]=mapped_column(String(255))
    s3_key: Mapped[str]=mapped_column(String(500))
    preview_key: Mapped[str | None]=mapped_column(String(500),nullable=True)
    preview_content_type: Mapped[str | None]=mapped_column(String(120),nullable=True)
    content_type: Mapped[str]=mapped_column(String(120))
    size_bytes: Mapped[int]=mapped_column(Integer)
    status: Mapped[str]=mapped_column(String(30),default="uploaded")
    uploaded_at: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))

class Version(Base):
    __tablename__="versions"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    upload_id: Mapped[int]=mapped_column(ForeignKey("upload_log.id"))
    slug: Mapped[str]=mapped_column(String(80),index=True)
    title: Mapped[str]=mapped_column(String(255))
    version: Mapped[str]=mapped_column(String(50))
    date: Mapped[str]=mapped_column(String(20))
    authors: Mapped[str]=mapped_column(String(500))
    summary: Mapped[str]=mapped_column(Text)
    is_latest: Mapped[bool]=mapped_column(Boolean,default=True)
    published_at: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))

class BenchmarkRun(Base):
    __tablename__="benchmark_runs"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    run_id: Mapped[str]=mapped_column(String(64),unique=True,index=True)
    domain: Mapped[str]=mapped_column(String(40),index=True)
    mode: Mapped[str]=mapped_column(String(40),index=True)
    results_json: Mapped[str]=mapped_column(Text)
    summary_json: Mapped[str]=mapped_column(Text)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))

class PrototypeRun(Base):
    __tablename__="prototype_runs"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    run_id: Mapped[str]=mapped_column(String(64),unique=True,index=True)
    domain: Mapped[str]=mapped_column(String(40),index=True)
    action: Mapped[str]=mapped_column(String(80))
    entity_id: Mapped[str]=mapped_column(String(120))
    agent_id: Mapped[str]=mapped_column(String(120))
    fault_type: Mapped[str | None]=mapped_column(String(60),nullable=True)
    fault_severity: Mapped[str | None]=mapped_column(String(30),nullable=True)
    decision: Mapped[str]=mapped_column(String(40))
    blocked_reason: Mapped[str | None]=mapped_column(Text,nullable=True)
    summary_json: Mapped[str]=mapped_column(Text)
    certificate_json: Mapped[str | None]=mapped_column(Text,nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))

class ComparisonStat(Base):
    __tablename__="comparison_stats"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    domain: Mapped[str]=mapped_column(String(40),index=True)
    mode: Mapped[str]=mapped_column(String(40))
    precision: Mapped[float]=mapped_column(Float)
    recall: Mapped[float]=mapped_column(Float)
    f1: Mapped[float]=mapped_column(Float)
    false_block_rate: Mapped[float]=mapped_column(Float)
    unsafe_prevented: Mapped[int]=mapped_column(Integer)
    task_success: Mapped[float]=mapped_column(Float)
    avg_latency_ms: Mapped[float]=mapped_column(Float)
    token_overhead: Mapped[int]=mapped_column(Integer)
    recorded_at: Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))
