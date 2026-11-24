import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv
load_dotenv()
DATABASE_URL=os.getenv("DATABASE_URL","sqlite:///./tooltruth.db")
connect_args={"check_same_thread":False} if DATABASE_URL.startswith("sqlite") else {}
engine=create_engine(DATABASE_URL,pool_pre_ping=True,connect_args=connect_args)
SessionLocal=sessionmaker(bind=engine,autocommit=False,autoflush=False)
class Base(DeclarativeBase): pass
def get_db():
    db=SessionLocal()
    try: yield db
    finally: db.close()
def init_db():
    from models import Admin, UploadLog, Version, BenchmarkRun, PrototypeRun, ComparisonStat
    from gateway.models import EventLog, EvidenceNode, EvidenceEdge
    Base.metadata.create_all(bind=engine)
    inspector=inspect(engine)
    additions={"preview_key":"VARCHAR(500)","preview_content_type":"VARCHAR(120)",
               "dependencies_json":"TEXT"}
    # Existing installations are migrated without destroying data.
    for table, column, sql_type in [("upload_log",n,t) for n,t in list(additions.items())[:2]] + [("event_logs","dependencies_json","TEXT")]:
        columns={c["name"] for c in inspector.get_columns(table)}
        if column not in columns:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
