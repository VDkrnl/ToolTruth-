import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tooltruth.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    # Import ALL models so that Base.metadata knows every table.
    from models import Admin, UploadLog, Version, BenchmarkRun, PrototypeRun, ComparisonStat  # noqa: F401
    from gateway.models import EventLog, EvidenceNode, EvidenceEdge  # noqa: F401
    from gateway.models import ShopifyWebhookEvent, OrderAttempt  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # --- forward-migration: add columns that older DBs are missing ---
    inspector = inspect(engine)
    additions = {
        "preview_key": "VARCHAR(500)",
        "preview_content_type": "VARCHAR(120)",
        "dependencies_json": "TEXT",
    }
    for table, column, sql_type in (
        [("upload_log", n, t) for n, t in list(additions.items())[:2]]
        + [("event_logs", "dependencies_json", "TEXT")]
    ):
        cols = {c["name"] for c in inspector.get_columns(table)}
        if column not in cols:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
