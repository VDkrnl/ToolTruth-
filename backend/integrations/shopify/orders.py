"""Create a Shopify draft order / order and prove it exists. Server-side only.

Sequence used by the gateway (gateway/order_flow.py):
  1. create_draft_order  - tagged with a key derived from the customer's idempotency key
  2. complete_draft_order - turns it into a real order with payment pending (no payment is taken)
  3. verify_order / verify_draft - read it back from Shopify and compare lines
If any step ends with an unknown outcome (timeout), find_by_tag() looks for the tagged record
before anything is retried.
"""
import hashlib
import re
from datetime import datetime, timedelta, timezone

from .errors import OrderExecutionError, ShopifyError
from .queries import (DRAFT_ORDER_BY_ID, DRAFT_ORDER_COMPLETE, DRAFT_ORDER_CREATE,
                      DRAFT_ORDERS_BY_TAG, ORDER_BY_ID)

RESERVE_MINUTES = 30


def idempotency_tag(key: str) -> str:
    """Shopify tag that identifies one customer attempt. Hashed so the raw key is never exposed."""
    return "tt-" + hashlib.sha256(key.encode()).hexdigest()[:32]


def _user_errors(payload: dict, field: str):
    errors = (payload.get(field) or {}).get("userErrors") or []
    if errors:
        text = "; ".join(e.get("message", "") for e in errors)[:300]
        raise OrderExecutionError("shopify_rejected", f"Shopify rejected the request: {text}")


def create_draft_order(client, lines: list[dict], email: str, tag: str, run_id: str,
                       reserve: bool = True, now: datetime | None = None) -> dict:
    """lines: [{"variant_id": gid, "quantity": int}]. Returns {"id", "name", "status"}."""
    draft_input = {
        "lineItems": [{"variantId": l["variant_id"], "quantity": l["quantity"]} for l in lines],
        "email": email,
        "tags": ["tooltruth", tag],
        "note": f"Placed through ToolTruth after verification. Run {run_id}.",
        "customAttributes": [{"key": "tooltruth_run_id", "value": run_id}],
    }
    if reserve:
        until = (now or datetime.now(timezone.utc)) + timedelta(minutes=RESERVE_MINUTES)
        draft_input["reserveInventoryUntil"] = until.strftime("%Y-%m-%dT%H:%M:%SZ")
    data = client.graphql(DRAFT_ORDER_CREATE, {"input": draft_input}, mutation=True)
    _user_errors(data, "draftOrderCreate")
    draft = (data.get("draftOrderCreate") or {}).get("draftOrder") or {}
    if not draft.get("id"):
        raise OrderExecutionError("no_draft_returned", "Shopify did not return a draft order.")
    return {"id": draft["id"], "name": draft.get("name"), "status": draft.get("status")}


def complete_draft_order(client, draft_id: str) -> dict:
    """Completes the draft with payment pending. Returns {"order_id","order_name","draft_status"}."""
    try:
        data = client.graphql(DRAFT_ORDER_COMPLETE, {"id": draft_id, "paymentPending": True}, mutation=True)
        _user_errors(data, "draftOrderComplete")
    except OrderExecutionError as exc:
        raise OrderExecutionError(exc.code, exc.message, draft_id=draft_id) from None
    draft = (data.get("draftOrderComplete") or {}).get("draftOrder") or {}
    order = draft.get("order") or {}
    if not order.get("id"):
        raise OrderExecutionError("no_order_returned",
                                  "Shopify completed the draft but returned no order.", draft_id=draft_id)
    return {"order_id": order["id"], "order_name": order.get("name"), "draft_status": draft.get("status")}


def find_by_tag(client, tag: str) -> dict | None:
    """Look for a record this system created earlier. Returns
    {"draft_id","draft_name","draft_status","order_id","order_name"} or None."""
    if not re.fullmatch(r"tt-[0-9a-f]{32}", tag):
        raise ValueError("bad tag")
    data = client.graphql(DRAFT_ORDERS_BY_TAG, {"query": f"tag:{tag}"})
    for edge in (data.get("draftOrders") or {}).get("edges", []):
        node = edge.get("node") or {}
        if tag in (node.get("tags") or []):
            order = node.get("order") or {}
            return {"draft_id": node.get("id"), "draft_name": node.get("name"),
                    "draft_status": node.get("status"),
                    "order_id": order.get("id"), "order_name": order.get("name")}
    return None


def _line_map(node: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in (node.get("lineItems") or {}).get("edges", []):
        n = e.get("node") or {}
        vid = (n.get("variant") or {}).get("id")
        if vid:
            out[vid] = out.get(vid, 0) + int(n.get("quantity") or 0)
    return out


def _compare(actual: dict[str, int], expected: list[dict]) -> str | None:
    want: dict[str, int] = {}
    for l in expected:
        want[l["variant_id"]] = want.get(l["variant_id"], 0) + l["quantity"]
    if actual != want:
        return "Shopify's record does not match the verified cart (lines or quantities differ)."
    return None


def verify_order(client, order_id: str, expected: list[dict], tag: str | None = None) -> dict:
    """Read the order back from Shopify. Returns {"verified": bool, "reason": str, ...}."""
    try:
        node = (client.graphql(ORDER_BY_ID, {"id": order_id}).get("order")) or None
    except ShopifyError as exc:
        return {"verified": False, "level": "unverified", "reason": f"Could not read the order back: {exc}"}
    if not node:
        return {"verified": False, "level": "unverified", "reason": "Shopify has no order with that ID."}
    mismatch = _compare(_line_map(node), expected)
    if mismatch:
        return {"verified": False, "level": "mismatch", "reason": mismatch, "order_name": node.get("name")}
    if tag and tag not in (node.get("tags") or []):
        # Orders created from a draft normally inherit its tags; absence is noted, not fatal.
        note = " (tag not copied to order)"
    else:
        note = ""
    return {"verified": True, "level": "order", "order_name": node.get("name"),
            "financial_status": node.get("displayFinancialStatus"), "created_at": node.get("createdAt"),
            "reason": "Order found in Shopify; lines and quantities match the verified cart." + note}


def verify_draft(client, draft_id: str, expected: list[dict]) -> dict:
    try:
        node = (client.graphql(DRAFT_ORDER_BY_ID, {"id": draft_id}).get("draftOrder")) or None
    except ShopifyError as exc:
        return {"verified": False, "level": "unverified", "reason": f"Could not read the draft order back: {exc}"}
    if not node:
        return {"verified": False, "level": "unverified", "reason": "Shopify has no draft order with that ID."}
    mismatch = _compare(_line_map(node), expected)
    if mismatch:
        return {"verified": False, "level": "mismatch", "reason": mismatch}
    return {"verified": True, "level": "draft", "order_name": node.get("name"),
            "reason": "Draft order found in Shopify; lines and quantities match the verified cart."}
