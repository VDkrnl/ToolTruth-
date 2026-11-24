"""agent/runner.py — build the guarded agent and run one chat turn (shared by CLI and service)."""
import uuid

from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware

from agent.budget import extract_budget
from agent.build import build_agent
from agent.client import ToolTruthClient
from agent.config import AgentSettings
from agent.context import RunContext
from agent.middleware import make_guard
from agent.prompts import SYSTEM_PROMPT, SHOPIFY_CONTENT_SYSTEM_PROMPT
from agent.tools import ALL_TOOLS
from agent.content_tools import CONTENT_TOOLS


def make_agent(settings: AgentSettings, client: ToolTruthClient):
    """Build an agent configured for the mode declared in settings.agent_mode.

    Modes
    -----
    shopping        — standard shopping agent (search, buy).
    shopify_content — Shopify store content management (products, pages, blogs, …).
    """
    if settings.agent_mode == "shopify_content":
        tools = CONTENT_TOOLS
        system_prompt = SHOPIFY_CONTENT_SYSTEM_PROMPT
    else:
        tools = ALL_TOOLS
        system_prompt = SYSTEM_PROMPT

    mw = [make_guard(client),
          ToolCallLimitMiddleware(run_limit=settings.max_tool_calls),
          ModelCallLimitMiddleware(run_limit=settings.max_model_calls)]
    return build_agent(settings, tools, system_prompt, mw)


def run_chat(agent, settings: AgentSettings, message: str, session_id: str | None = None,
             budget_minor: int | None = None, currency: str | None = None,
             fault: str | None = None) -> dict:
    sid = session_id or "s-" + uuid.uuid4().hex[:10]
    if budget_minor is None:  # UI field wins; otherwise deterministic regex over the raw message
        found = extract_budget(message)
        if found:
            budget_minor, currency = found
    ctx = RunContext(session_id=sid, budget_minor=budget_minor, currency=currency, fault=fault)
    result = agent.invoke({"messages": [("human", message)]},
                          config={"configurable": {"thread_id": sid}}, context=ctx)
    trace, answer = [], ""
    msgs = result["messages"]
    # The checkpointer keeps the whole session; report only THIS turn (after the last human message),
    # otherwise the UI re-shows an earlier turn's decision.
    start = max((i for i, m in enumerate(msgs) if m.type == "human"), default=0)
    for m in msgs[start:]:
        for tc in getattr(m, "tool_calls", None) or []:
            trace.append({"type": "tool_call", "name": tc["name"], "args": tc["args"]})
        if m.type == "tool":
            trace.append({"type": "tool_result", "name": m.name, "status": m.status, "content": m.content,
                          "envelope": getattr(m, "artifact", None)})
        elif m.type == "ai" and m.content and not getattr(m, "tool_calls", None):
            answer = m.content
    return {"session_id": sid, "answer": answer, "trace": trace,
            "mode": "llm" if settings.model else "scripted"}
