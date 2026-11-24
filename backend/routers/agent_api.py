"""/agent/* — gateway endpoints used only by the agent service (X-Agent-Key)."""
import hmac
import os

import threading
import time
from collections import deque

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from engine.certificate import verify_certificate_v3
from database import get_db
from services import agent_shopify, agent_shopify_content, agent_sim as sim

router = APIRouter(prefix="/agent", tags=["agent"])


def _auth(key: str | None):
    expected = os.getenv("TT_AGENT_API_KEY", "")
    if not expected:
        raise HTTPException(503, "agent API not configured")  # fail closed
    if not key or not hmac.compare_digest(key, expected):
        raise HTTPException(401, "invalid agent key")


class ReadReq(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=120)
    args: dict = {}


class RunCtx(BaseModel):
    model_config = ConfigDict(extra="forbid")
    budget_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    fault: str | None = Field(default=None, max_length=40)   # demo fault injection; ignored unless TT_DEMO_FAULTS=1


class WriteReq(ReadReq):
    run_context: RunCtx = RunCtx()


def _shopify() -> bool:
    return os.getenv("TT_PROVIDER", "shopify").lower() == "shopify"


def _shopify_content() -> bool:
    return os.getenv("TT_PROVIDER", "shopify").lower() == "shopify_content"


_order_hits: deque = deque()
_order_lock = threading.Lock()


def _order_rate_limit(limit: int = 4, window: int = 60):
    """Stay under Shopify's dev-store limit of 5 new orders/minute."""
    now = time.monotonic()
    with _order_lock:
        while _order_hits and now - _order_hits[0] > window:
            _order_hits.popleft()
        if len(_order_hits) >= limit:
            raise HTTPException(429, "order rate limit reached", headers={"Retry-After": str(window)})
        _order_hits.append(now)


def _check_args(tool, args):
    extra = set(args) - sim.ALLOWED_ARGS[tool]
    if extra:
        raise HTTPException(422, f"unexpected args: {sorted(extra)}")


@router.get("/tools")
def tools(x_agent_key: str | None = Header(None)):
    _auth(x_agent_key)
    if _shopify_content():
        from agent.content_tools import CONTENT_TOOLS
        return {
            "tools": [t.name for t in CONTENT_TOOLS],
            "provider": "shopify_content",
        }
    return {"tools": sim.TOOLS, "provider": "shopify" if _shopify() else "simulator"}


@router.post("/read/{tool}")
def read(tool: str, body: ReadReq, x_agent_key: str | None = Header(None), db=Depends(get_db)):
    _auth(x_agent_key)
    # ── Shopify Content agent ──────────────────────────────────────────────
    if _shopify_content():
        from agent.content_tools import CONTENT_READ_TOOLS
        if tool not in CONTENT_READ_TOOLS:
            raise HTTPException(422, f"unknown content read tool '{tool}'")
        return agent_shopify_content.read(tool, body.session_id, body.args, db)
    # ── Shopping agent (default) ───────────────────────────────────────────
    if tool not in sim.ALLOWED_ARGS or tool == "create_test_order":
        raise HTTPException(422, f"unknown read tool '{tool}'")
    _check_args(tool, body.args)
    if _shopify():
        return agent_shopify.read(tool, body.session_id, body.args, db)
    return sim.read(tool, body.session_id, body.args)


@router.post("/write/{tool}")
def write(tool: str, body: WriteReq, x_agent_key: str | None = Header(None), db=Depends(get_db)):
    _auth(x_agent_key)
    # ── Shopify Content agent ──────────────────────────────────────────────
    if _shopify_content():
        from agent.content_tools import CONTENT_WRITE_TOOLS
        if tool not in CONTENT_WRITE_TOOLS:
            raise HTTPException(422, f"unknown content write tool '{tool}'")
        return agent_shopify_content.write(tool, body.session_id, body.args, db)
    # ── Shopping agent (default) ───────────────────────────────────────────
    if tool != "create_test_order":
        raise HTTPException(422, f"unknown write tool '{tool}'")
    _check_args(tool, body.args)
    ctx = body.run_context.model_dump()
    if _shopify():
        _order_rate_limit()
        return agent_shopify.write(body.session_id, body.args, ctx, db)
    return sim.write(body.session_id, body.args, ctx)


@router.get("/runs/{run_id}")
def run(run_id: str, x_agent_key: str | None = Header(None)):
    _auth(x_agent_key)
    r = sim.get_run(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    return r


@router.get("/certificates/{cid}")
def cert(cid: str, x_agent_key: str | None = Header(None)):
    _auth(x_agent_key)
    c = sim.get_cert(cid)
    if not c:
        raise HTTPException(404, "certificate not found")
    return c


@router.get("/certificates/{cid}/verify")
def verify(cid: str, x_agent_key: str | None = Header(None)):
    _auth(x_agent_key)
    c = sim.get_cert(cid)
    if not c:
        raise HTTPException(404, "certificate not found")
    return {"valid": verify_certificate_v3(c)}


@router.post("/reconcile/{run_id}")
def reconcile(run_id: str, x_agent_key: str | None = Header(None), db=Depends(get_db)):
    _auth(x_agent_key)
    if not _shopify():
        raise HTTPException(409, "reconcile applies to the shopify provider only")
    env = agent_shopify.reconcile(run_id, db)
    if env is None:
        raise HTTPException(404, "no uncertain run with that id")
    return env
