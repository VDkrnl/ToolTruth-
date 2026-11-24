"""agent/middleware.py — the single choke point: every tool call is forwarded to ToolTruth."""
import json

from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage

from agent.client import GatewayUnavailable

KNOWN = {"search_products", "get_product_details", "check_inventory", "create_test_order"}
WRITE = {"create_test_order"}


def _msg(request, content, error=False, env=None):
    tc = request.tool_call
    return ToolMessage(content=content, tool_call_id=tc["id"], name=tc["name"],
                       status="error" if error else "success", artifact=env)  # artifact: for the UI only


def render_read(env: dict) -> str:
    if env.get("errors"):
        return f"TT_READ=error errors={env['errors']}"
    head = f"TT_READ=ok provider={env['provider']} live={env['live']} observation_id={env['observation_id']}"
    res = env["result"]
    items = res["items"] if "items" in res else [res]
    def money(i):
        return f"{i['price_minor'] / 100:,.2f} {i['currency']}" if i.get("price_minor") is not None else "unknown"
    lines = [f"{i['name']} | sku={i['sku']} | price={money(i)} (major units) | in_stock={i['available']} | "
             f"variant_id={i['variant_id']} observation_id={env['observation_id']}" for i in items]
    return head + "\n" + ("\n".join(lines) if lines else "no products found")


def render_write(env: dict) -> tuple[str, bool]:
    d, ex, po = env["decision"], env["execution"], env["postcondition"]
    verified = "verified" if po.get("verified") else ("unverified" if ex["attempted"] else "n/a")
    head = f"TT_DECISION={d['outcome']} TT_EXEC={ex['state']} TT_POST={verified} RUN={env['run_id']}"
    cert = env.get("certificate", {}).get("id", "")
    if d["outcome"] == "allow":
        if ex["state"] == "succeeded" and po.get("verified"):
            return f"{head}\nOrder {ex['order_ref']} created and verified. Certificate {cert}. [{env['provider']}]", False
        if ex["state"] == "succeeded":
            return f"{head}\nOrder created but NOT verified; needs human review.", True
        return f"{head}\nExecution failed: {ex['error']}. No order was created.", True
    if d["outcome"] == "block":
        return (f"{head}\nBlocked: {d['reason']} Failed checks: {d['failed_checks']}. "
                "Do not retry the same request; tell the user why."), True
    return (f"{head}\nMore evidence needed: {d['reason']} Call check_inventory again or ask the user. "
            "No action was taken."), False


def make_guard(client):
    @wrap_tool_call
    def tooltruth_guard(request, handler):
        tc, ctx = request.tool_call, request.runtime.context  # ctx = trusted RunContext
        name = tc["name"]
        if name not in KNOWN:
            return _msg(request, f"Tool '{name}' is not registered. Refused.", True)
        try:
            if name in WRITE:
                env = client.write(name, tc["args"], ctx.session_id,
                                   {"budget_minor": ctx.budget_minor, "currency": ctx.currency,
                                    "fault": ctx.fault})
                text, err = render_write(env)
                return _msg(request, text, err, env)
            env = client.read(name, tc["args"], ctx.session_id)
            return _msg(request, render_read(env), env=env)
        except GatewayUnavailable as e:  # fail CLOSED: never execute directly
            return _msg(request, f"ToolTruth gateway unavailable ({e.code}). No action was taken.", True)
    return tooltruth_guard
