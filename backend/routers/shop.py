"""Customer storefront API (public) and order monitoring (admin).

Public:  GET /shop/catalog, POST /shop/orders, GET /shop/orders/{run_id}
Admin:   GET /shop/admin/orders, GET /shop/admin/monitor

Shopify credentials never leave the server. The browser only ever talks to these routes, and
POST /shop/orders is the single door to order creation: it always verifies first (gateway/order_flow.py).
"""
import json
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from auth import current_admin
from database import get_db
from gateway.models import OrderAttempt, ShopifyWebhookEvent
from gateway.order_flow import MAX_QTY, OrderService
from integrations.shopify import get_client
from integrations.shopify.catalog import fetch_all_variants, resolve_level
from integrations.shopify.config import ORDER_SCOPES, REQUIRED_SCOPES, load_settings
from integrations.shopify.errors import ShopifyError
from integrations.shopify.queries import SHOP_INFO

router = APIRouter(prefix="/shop", tags=["shop"])


# --------------------------------------------------------------------------- rate limiting
class _RateLimiter:
    """Sliding window per client address. In-memory: enough to stop a single browser from
    hammering Shopify; put a real limiter in front of the API for anything larger."""

    def __init__(self, limit: int, window_seconds: int = 60):
        self.limit, self.window = limit, window_seconds
        self.hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, request: Request) -> None:
        fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        who = fwd or (request.client.host if request.client else "unknown")
        now = time.monotonic()
        with self._lock:
            q = self.hits[who]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                raise HTTPException(429, "Too many requests. Please wait a minute and try again.")
            q.append(now)


catalog_limiter = _RateLimiter(int(os.getenv("SHOP_RATE_LIMIT_CATALOG", "60")))
order_limiter = _RateLimiter(int(os.getenv("SHOP_RATE_LIMIT_ORDERS", "10")))


# --------------------------------------------------------------------------- catalog
def _variant_status(v: dict, level, code: str | None) -> tuple[str, bool]:
    if not v["sku"]:
        return "no_sku", False
    if code in ("inventory_not_tracked",):
        return "untracked", False
    if code:
        return "location_unresolved", False
    return ("in_stock", True) if level["quantities"]["available"] > 0 else ("out_of_stock", False)


@router.get("/catalog")
def catalog(request: Request):
    catalog_limiter.check(request)
    settings = load_settings()
    if not settings.configured:
        raise HTTPException(503, "The store is not connected yet.")
    try:
        variants, currency, fetched_at = fetch_all_variants(get_client())
    except ShopifyError as exc:
        raise HTTPException(502, f"Could not load the catalog from Shopify: {exc}")
    products: dict[str, dict] = {}
    for v in variants:
        if v["product_status"] != "ACTIVE":
            continue                     # draft/archived products are never shown to customers
        level, code, _why = resolve_level(v, settings.default_location_id)
        status, purchasable = _variant_status(v, level, code)
        p = products.setdefault(v["product_id"], {
            "product_id": v["product_id"], "title": v["product_title"], "image_url": v["image_url"], "variants": []})
        p["image_url"] = p["image_url"] or v["image_url"]
        p["variants"].append({
            "sku": v["sku"], "title": v["variant_title"], "price": v["price"], "image_url": v["image_url"],
            "available": level["quantities"]["available"] if level else None,
            "max_quantity": min(level["quantities"]["available"], MAX_QTY) if level and purchasable else 0,
            "status": status, "purchasable": purchasable,
            "stock_updated_at": level["source_updated_at"] if level else None})
    return {"currency": currency, "fetched_at": fetched_at.isoformat(),
            "orders_enabled": settings.orders_enabled, "max_quantity": MAX_QTY,
            "products": list(products.values())}


# --------------------------------------------------------------------------- orders
class OrderBody(BaseModel):
    # Deliberately loose: OrderService validates every field and records failures as a BLOCK.
    idempotency_key: str = Field(max_length=200)
    items: list[dict] = Field(default_factory=list, max_length=50)
    customer: dict = Field(default_factory=dict)
    observed_at: str | None = Field(default=None, max_length=64)
    max_age_seconds: int | None = None


@router.post("/orders")
def place_order(body: OrderBody, request: Request, db: Session = Depends(get_db)):
    order_limiter.check(request)
    req = body.model_dump()
    if len(json.dumps(req, default=str)) > 10_000:
        raise HTTPException(400, "Request too large")
    if not load_settings().configured:
        raise HTTPException(503, "The store is not connected yet.")
    out = OrderService(db).place_order(req)
    status = out.pop("http_status", 200)
    if status != 200:
        from fastapi.responses import JSONResponse
        return JSONResponse(out, status_code=status)
    return out


@router.get("/orders/{run_id}")
def get_order(run_id: str, request: Request, db: Session = Depends(get_db)):
    catalog_limiter.check(request)
    if len(run_id) > 64:
        raise HTTPException(404, "Order run not found")
    out = OrderService(db).get_result(run_id)
    if out is None:
        raise HTTPException(404, "Order run not found")
    out.pop("http_status", None)
    return out


# --------------------------------------------------------------------------- admin monitoring
def _summary_row(a: OrderAttempt) -> dict:
    return {"run_id": a.run_id, "status": a.status, "decision": a.decision, "reason": a.reason,
            "items": [{"sku": c["sku"], "quantity": c["quantity"]} for c in json.loads(a.cart_json or "[]")],
            "order_name": a.shopify_order_name, "order_id": a.shopify_order_id, "mode": a.order_mode,
            "order_entity_id": f"shopify-order:{a.run_id}",
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None}


@router.get("/admin/orders")
def admin_orders(limit: int = 50, db: Session = Depends(get_db), _=Depends(current_admin)):
    rows = db.query(OrderAttempt).order_by(OrderAttempt.id.desc()).limit(max(1, min(limit, 200))).all()
    return [_summary_row(a) for a in rows]


@router.get("/admin/monitor")
def admin_monitor(db: Session = Depends(get_db), _=Depends(current_admin)):
    s = load_settings()
    out = {"configured": s.configured, "store_domain": s.store_domain or None, "api_version": s.api_version,
           "orders_enabled": s.orders_enabled, "order_mode": s.order_mode}
    if s.configured:
        try:
            client = get_client()
            shop = client.graphql(SHOP_INFO).get("shop") or {}
            granted = list(client.tokens.scopes)
            out["connection"] = {"ok": True, "shop_name": shop.get("name"), "scopes": granted,
                                 "missing_read_scopes": [x for x in REQUIRED_SCOPES if x not in granted],
                                 "missing_order_scopes": [x for x in ORDER_SCOPES if x not in granted]}
        except ShopifyError as exc:
            out["connection"] = {"ok": False, "error": str(exc)}
    counts = dict(db.query(OrderAttempt.status, func.count(OrderAttempt.id)).group_by(OrderAttempt.status).all())
    day_ago = (datetime.now(timezone.utc) - timedelta(hours=24)).replace(tzinfo=None)
    decisions = dict(db.query(OrderAttempt.decision, func.count(OrderAttempt.id))
                     .filter(OrderAttempt.created_at >= day_ago).group_by(OrderAttempt.decision).all())
    last_hook = db.query(func.max(ShopifyWebhookEvent.received_at)).scalar()
    out.update({
        "attempts_by_status": counts,
        "decisions_last_24h": {k or "unknown": v for k, v in decisions.items()},
        "needs_attention": counts.get("uncertain", 0) + counts.get("executed_unverified", 0) + counts.get("execution_failed", 0),
        "last_inventory_webhook_at": last_hook.isoformat() if last_hook else None,
        "recent": [_summary_row(a) for a in db.query(OrderAttempt).order_by(OrderAttempt.id.desc()).limit(15).all()]})
    return out
