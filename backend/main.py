import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from database import init_db
from routers import auth, uploads, publish, versions, files, gateway, benchmark, prototype


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="ToolTruth API",
    version="2.0.0",
    description="Deterministic typed consistency gateway for AI-agent tool calls.",
    lifespan=lifespan,
)

origins = [
    x.strip()
    for x in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5500,http://127.0.0.1:5500",
    ).split(",")
    if x.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(uploads.router)
app.include_router(publish.router)
app.include_router(versions.router)
app.include_router(files.router)
app.include_router(gateway.router)
app.include_router(benchmark.router)
app.include_router(prototype.router)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "tooltruth-api", "version": "2.0.0"}
