"""agent/service.py — chat service. Run: uvicorn agent.service:app --port 8100

Imports only agent.* and httpx/fastapi: no Shopify credentials, no DB.
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent.client import ToolTruthClient
from agent.config import load_settings
from agent.runner import make_agent, run_chat

app = FastAPI(title="ToolTruth Agent Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv(
        "CORS_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500").split(",") if o.strip()],
    allow_methods=["GET", "POST"], allow_headers=["*"],
)

_state: dict = {}


def get_agent():
    if "agent" not in _state:
        s = load_settings()
        _state.update(settings=s, agent=make_agent(s, ToolTruthClient(s)))
    return _state["settings"], _state["agent"]


class ChatReq(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    session_id: str | None = Field(default=None, max_length=120)
    budget_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    fault: str | None = Field(default=None, max_length=40)


@app.get("/health")
def health():
    settings = load_settings()
    return {"status": "ok", "mode": "llm" if settings.model else "scripted",
            "gateway_provider": ToolTruthClient(settings).provider()}


@app.post("/chat")
def chat(req: ChatReq):
    settings, agent = get_agent()
    return run_chat(agent, settings, req.message, req.session_id, req.budget_minor, req.currency, req.fault)


class RaceReq(BaseModel):
    sku: str = Field(default="TT-002", pattern=r"^[A-Za-z0-9._-]{1,64}$")
    budget_minor: int = Field(default=500000, ge=0)


@app.post("/demo/race")
def demo_race(req: RaceReq):
    """Two buyers observe the same stock, then both try to buy it at the same moment (not the LLM)."""
    import threading
    settings, _ = get_agent()
    client = ToolTruthClient(settings)
    probe = client.read("check_inventory", {"sku": req.sku}, "race-probe")
    item = probe.get("result") or {}
    available = item.get("available") or 0
    qty = max(1, min(2, available))
    if available < qty or available >= 2 * qty:
        return {"ran": False, "available": available, "quantity": qty,
                "note": f"A race needs stock between {qty} and {2 * qty - 1} so only one buyer can win; "
                        f"current stock is {available}."}
    gate, out = threading.Barrier(2), {}

    def buyer(name):
        sid = f"race-{name}-" + os.urandom(3).hex()
        obs = client.read("check_inventory", {"sku": req.sku}, sid)
        gate.wait(timeout=10)
        try:
            out[name] = client.write("create_test_order", {"variant_id": item["variant_id"], "sku": req.sku,
                                     "quantity": qty, "observation_id": obs["observation_id"]}, sid,
                                     {"budget_minor": req.budget_minor, "currency": "INR"})
        except Exception as e:  # noqa: BLE001
            out[name] = {"error": str(e)}

    ts = [threading.Thread(target=buyer, args=(n,)) for n in ("A", "B")]
    [t.start() for t in ts]
    [t.join(timeout=60) for t in ts]
    return {"ran": True, "available": available, "quantity": qty, "buyers": out}
