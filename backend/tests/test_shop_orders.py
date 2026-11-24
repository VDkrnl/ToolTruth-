"""Tests for the customer order flow: verify -> decide -> create -> prove.
A stateful fake Shopify (httpx.MockTransport) stands in for the store; no internet needed."""
import json
import re
import threading
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from auth import hash_password
from database import SessionLocal
from gateway.models import EvidenceNode, EventLog, OrderAttempt
from gateway.order_flow import OrderService
from integrations.shopify import ShopifyClient, set_client
from integrations.shopify.config import ShopifySettings
from main import app
from models import Admin
from routers import shop as shop_router

SECRET = "shpss_test_secret"
SETTINGS = ShopifySettings(store_domain="tt-test.myshopify.com", client_id="cid",
                           client_secret=SECRET, api_version="2026-10", orders_enabled=True)
ALL_SCOPES = "read_products,read_inventory,read_locations,write_draft_orders,read_draft_orders,read_orders"
CUSTOMER = {"name": "Demo Customer", "email": "demo@example.com"}
T0 = "2026-11-01T10:00:00Z"


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeShop:
    """Stateful: completing a draft order really lowers 'available', like Shopify does."""

    def __init__(self):
        self.variants = {}
        self.drafts, self.orders = {}, {}
        self.scopes = ALL_SCOPES
        self.create_mode = "ok"       # ok | user_error | timeout_after_create | timeout_before_create
        self.complete_mode = "ok"     # ok | user_error | timeout_after
        self.tag_search = True
        self.readback = "ok"          # ok | mismatch | denied
        self.calls = []
        self.lock = threading.Lock()
        self.add("TT-001", stock=10, price="999.00", title="Laptop")
        self.add("TT-002", stock=1, price="49.00", title="Mouse")

    def add(self, sku, stock=5, price="10.00", title="Thing", status="ACTIVE", tracked=True, loc="456",
            updated=T0, on_hand=None):
        n = len(self.variants) + 1
        self.variants[sku] = {"id": f"gid://shopify/ProductVariant/{n}", "sku": sku, "title": "Default", "price": price,
                              "product": {"id": f"gid://shopify/Product/{n}", "title": title, "status": status,
                                          "featuredImage": None},
                              "item_id": f"gid://shopify/InventoryItem/{n}", "tracked": tracked,
                              "levels": {loc: {"name": "Warehouse A", "available": stock, "committed": 0,
                                               "on_hand": stock if on_hand is None else on_hand, "updated": updated}}}

    def set_stock(self, sku, n, loc="456", updated=None):
        lv = self.variants[sku]["levels"][loc]
        lv["available"], lv["on_hand"] = n, n + lv["committed"]
        lv["updated"] = updated or iso(datetime.now(timezone.utc))

    # ---- shapes
    def _node(self, v):
        levels = []
        for loc, lv in v["levels"].items():
            qs = [{"name": "available", "quantity": lv["available"], "updatedAt": lv["updated"]},
                  {"name": "on_hand", "quantity": lv["on_hand"], "updatedAt": lv["updated"]},
                  {"name": "committed", "quantity": lv["committed"], "updatedAt": lv["updated"]}]
            for n in ("reserved", "damaged", "safety_stock", "quality_control", "incoming"):
                qs.append({"name": n, "quantity": 0, "updatedAt": lv["updated"]})
            levels.append({"node": {"updatedAt": lv["updated"], "location": {"id": f"gid://shopify/Location/{loc}", "name": lv["name"]},
                                    "quantities": qs}})
        return {"id": v["id"], "sku": v["sku"], "title": v["title"], "price": v["price"], "image": None,
                "product": v["product"],
                "inventoryItem": {"id": v["item_id"], "tracked": v["tracked"], "inventoryLevels": {"edges": levels}}}

    def _lines(self, rec):
        return {"edges": [{"node": {"sku": l["sku"], "quantity": l["quantity"], "variant": {"id": l["variant_id"]}}}
                          for l in rec["lines"]]}

    def _by_vid(self, vid):
        return next((v for v in self.variants.values() if v["id"] == vid), None)

    # ---- transport
    def handler(self, request):
        if request.url.path.endswith("/oauth/access_token"):
            return httpx.Response(200, json={"access_token": "tok", "scope": self.scopes, "expires_in": 86399})
        body = json.loads(request.content)
        q, vars_ = body["query"], body.get("variables") or {}
        with self.lock:
            return self._dispatch(q, vars_)

    def _ok(self, data):
        return httpx.Response(200, json={"data": data})

    def _dispatch(self, q, v):
        if "query CatalogPage" in q:
            self.calls.append("catalog")
            skus = re.findall(r'sku:"([^"]+)"', v.get("query") or "")
            items = [x for x in self.variants.values() if not skus or x["sku"] in skus]
            start = int(v.get("after") or 0)
            size = v["first"]
            page = items[start:start + size]
            more = start + size < len(items)
            return self._ok({"shop": {"currencyCode": "INR"},
                             "productVariants": {"pageInfo": {"hasNextPage": more, "endCursor": str(start + size)},
                                                 "edges": [{"node": self._node(x)} for x in page]}})
        if "mutation DraftOrderCreate" in q:
            self.calls.append("create")
            inp = v["input"]
            if self.create_mode == "timeout_before_create":
                return httpx.Response(504, json={})
            if self.create_mode == "user_error":
                return self._ok({"draftOrderCreate": {"draftOrder": None, "userErrors": [{"field": ["x"], "message": "Boom"}]}})
            lines = []
            for li in inp["lineItems"]:
                var = self._by_vid(li["variantId"])
                lines.append({"sku": var["sku"], "quantity": li["quantity"], "variant_id": li["variantId"]})
            did = f"gid://shopify/DraftOrder/{len(self.drafts) + 1}"
            self.drafts[did] = {"id": did, "name": f"#D{len(self.drafts) + 1}", "status": "OPEN", "tags": inp["tags"],
                                "lines": lines, "order": None}
            if self.create_mode == "timeout_after_create":
                return httpx.Response(504, json={})
            d = self.drafts[did]
            return self._ok({"draftOrderCreate": {"draftOrder": {"id": did, "name": d["name"], "status": "OPEN", "tags": d["tags"]},
                                                  "userErrors": []}})
        if "mutation DraftOrderComplete" in q:
            self.calls.append("complete")
            d = self.drafts[v["id"]]
            assert v["paymentPending"] is True            # we never collect payment
            if self.complete_mode == "user_error":
                return self._ok({"draftOrderComplete": {"draftOrder": None, "userErrors": [{"field": None, "message": "Cannot complete"}]}})
            oid = f"gid://shopify/Order/{len(self.orders) + 1}"
            self.orders[oid] = {"id": oid, "name": f"#{1000 + len(self.orders) + 1}", "tags": d["tags"], "lines": d["lines"]}
            d["status"], d["order"] = "COMPLETED", {"id": oid, "name": self.orders[oid]["name"]}
            for l in d["lines"]:                           # committing the order takes stock
                lv = next(iter(self.variants[l["sku"]]["levels"].values()))
                lv["available"] -= l["quantity"]
                lv["committed"] += l["quantity"]
            if self.complete_mode == "timeout_after":
                return httpx.Response(504, json={})
            return self._ok({"draftOrderComplete": {"draftOrder": {"id": d["id"], "name": d["name"], "status": "COMPLETED", "order": d["order"]},
                                                    "userErrors": []}})
        if "query DraftOrdersByTag" in q:
            self.calls.append("find")
            tag = v["query"].split(":", 1)[1]
            hits = [d for d in self.drafts.values() if tag in d["tags"]] if self.tag_search else []
            return self._ok({"draftOrders": {"edges": [{"node": {"id": d["id"], "name": d["name"], "status": d["status"],
                                                                 "tags": d["tags"], "order": d["order"]}} for d in hits]}})
        if "query OrderById" in q:
            self.calls.append("readback")
            if self.readback == "denied":
                return httpx.Response(200, json={"errors": [{"message": "Access denied for order field."}]})
            o = self.orders.get(v["id"])
            if not o:
                return self._ok({"order": None})
            lines = [dict(l) for l in o["lines"]]
            if self.readback == "mismatch":
                lines[0]["quantity"] += 1
            return self._ok({"order": {"id": o["id"], "name": o["name"], "createdAt": T0, "tags": o["tags"],
                                       "displayFinancialStatus": "PENDING", "lineItems": self._lines({"lines": lines})}})
        if "query DraftOrderById" in q:
            self.calls.append("readback_draft")
            d = self.drafts.get(v["id"])
            return self._ok({"draftOrder": None if not d else {"id": d["id"], "name": d["name"], "status": d["status"],
                                                                "tags": d["tags"], "order": d["order"], "lineItems": self._lines(d)}})
        if "shop {" in q:
            return self._ok({"shop": {"name": "TT Test", "myshopifyDomain": "tt-test.myshopify.com"}})
        raise AssertionError("unexpected query: " + q[:60])


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, val in {"SHOPIFY_STORE_DOMAIN": SETTINGS.store_domain, "SHOPIFY_CLIENT_ID": "cid",
                   "SHOPIFY_CLIENT_SECRET": SECRET, "SHOPIFY_API_VERSION": "2026-10",
                   "SHOPIFY_ORDERS_ENABLED": "true"}.items():
        monkeypatch.setenv(k, val)
    monkeypatch.delenv("SHOPIFY_DEFAULT_LOCATION_ID", raising=False)
    monkeypatch.delenv("SHOPIFY_ORDER_MODE", raising=False)
    shop_router.order_limiter.hits.clear()
    shop_router.catalog_limiter.hits.clear()
    shop_router.order_limiter.limit = shop_router.catalog_limiter.limit = 1000
    set_client(None)
    yield
    set_client(None)


@pytest.fixture
def fake():
    f = FakeShop()
    set_client(ShopifyClient(SETTINGS, transport=httpx.MockTransport(f.handler), sleep=lambda s: None))
    return f


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def api():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_headers(api):
    d = SessionLocal()
    d.add(Admin(username="adm", password_hash=hash_password("pw-12345678")))
    d.commit()
    d.close()
    tok = api.post("/auth/login", json={"username": "adm", "password": "pw-12345678"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def order(key="key-00000001", items=None, **extra):
    body = {"idempotency_key": key, "items": [{"sku": "TT-001", "quantity": 2}] if items is None else items, "customer": CUSTOMER}
    body.update(extra)
    return body


def names(out, failed_only=True):
    return {c["name"] for c in out["checks"] if not (failed_only and c["passed"])}


# ============================================================ the seven demo scenarios
def test_1_valid_order_is_allowed_created_and_proven(fake, db):
    out = OrderService(db).place_order(order())
    assert out["decision"] == "allow" and out["status"] == "executed_verified"
    assert out["order"]["name"] == "#1001" and out["execution"]["verification"]["verified"]
    assert fake.calls.count("create") == 1 and fake.calls.count("complete") == 1 and "readback" in fake.calls
    assert fake.variants["TT-001"]["levels"]["456"]["available"] == 8       # Shopify really committed the stock
    # evidence: stock observation + order-level decision are stored and linked
    assert db.query(EvidenceNode).filter_by(entity_id="shopify:TT-001:456", claim="quantity_available=10").count() == 1
    claims = {n.claim for n in db.query(EvidenceNode).filter_by(entity_id=out["order_entity_id"])}
    assert {"decision=allow", "order_status=executed_verified", "shopify_order=#1001", "order_verified=true"} <= claims
    assert db.query(EventLog).filter_by(action="place_order").one().status == "allowed"


def test_2_insufficient_inventory_is_blocked_and_nothing_is_created(fake, db):
    out = OrderService(db).place_order(order(items=[{"sku": "TT-002", "quantity": 5}]))
    assert out["decision"] == "block" and out["status"] == "rejected"
    assert "sufficient_inventory" in names(out) and "only 1 available" in out["reason"]
    assert "create" not in fake.calls and not fake.orders and not fake.drafts


def test_3_unknown_sku_is_blocked(fake, db):
    out = OrderService(db).place_order(order(items=[{"sku": "NOPE-1", "quantity": 1}]))
    assert out["decision"] == "block" and "tool_result" in names(out) and "does not exist" in out["reason"]
    assert not fake.drafts


def test_4_stale_snapshot_requests_more_evidence(fake, db):
    old = iso(datetime.now(timezone.utc) - timedelta(minutes=30))
    out = OrderService(db).place_order(order(observed_at=old))
    assert out["decision"] == "request_more_evidence" and out["status"] == "needs_evidence"
    assert "freshness" in names(out) and "old" in out["reason"]
    assert not fake.drafts


def test_5_duplicate_request_never_creates_a_second_order(fake, db):
    first = OrderService(db).place_order(order())
    again = OrderService(db).place_order(order())
    assert again["replayed"] and again["run_id"] == first["run_id"] and again["order"]["name"] == "#1001"
    assert fake.calls.count("create") == 1 and len(fake.orders) == 1
    assert db.query(OrderAttempt).count() == 1


def test_5b_same_key_different_cart_is_a_conflict(fake, db):
    OrderService(db).place_order(order())
    out = OrderService(db).place_order(order(items=[{"sku": "TT-001", "quantity": 3}]))
    assert out["http_status"] == 409 and out["decision"] == "block" and len(fake.orders) == 1


def test_6_stock_changed_after_snapshot_requests_more_evidence(fake, db):
    seen_at = iso(datetime.now(timezone.utc) - timedelta(seconds=20))
    fake.set_stock("TT-001", 7)                                  # someone bought 3 since the page loaded
    out = OrderService(db).place_order(order(observed_at=seen_at,
                                             items=[{"sku": "TT-001", "quantity": 2, "observed_available": 10}]))
    assert out["decision"] == "request_more_evidence" and "changed from 10 to 7" in out["reason"]
    assert not fake.drafts


def test_6b_stock_changed_and_now_too_low_is_a_block(fake, db):
    fake.set_stock("TT-001", 1)
    out = OrderService(db).place_order(order(items=[{"sku": "TT-001", "quantity": 2, "observed_available": 10}]))
    assert out["decision"] == "block" and "only 1 available" in out["reason"]      # the BLOCK reason leads


def test_7_concurrent_orders_for_the_last_unit_create_exactly_one_order(fake):
    results, errors = [], []

    def go(i):
        s = SessionLocal()
        try:
            results.append(OrderService(s).place_order(order(key=f"concurrent-key-{i}", items=[{"sku": "TT-002", "quantity": 1}])))
        except Exception as exc:                                  # pragma: no cover
            errors.append(exc)
        finally:
            s.close()
    threads = [threading.Thread(target=go, args=(i,)) for i in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert sorted(r["decision"] for r in results) == ["allow", "block", "block", "block", "block"]
    assert len(fake.orders) == 1 and fake.variants["TT-002"]["levels"]["456"]["available"] == 0


# ============================================================ more safety behaviour
def test_inactive_product_is_blocked(fake, db):
    fake.add("TT-DRAFT", status="DRAFT")
    out = OrderService(db).place_order(order(items=[{"sku": "TT-DRAFT", "quantity": 1}]))
    assert out["decision"] == "block" and "product_active" in names(out)


def test_untracked_inventory_is_blocked(fake, db):
    fake.add("TT-UNTRACKED", tracked=False)
    out = OrderService(db).place_order(order(items=[{"sku": "TT-UNTRACKED", "quantity": 1}]))
    assert out["decision"] == "block" and "tool_result" in names(out)


def test_inconsistent_shopify_numbers_request_more_evidence(fake, db):
    fake.add("TT-ODD", stock=5, on_hand=99)
    out = OrderService(db).place_order(order(items=[{"sku": "TT-ODD", "quantity": 1}]))
    assert out["decision"] == "request_more_evidence" and "source_consistency" in names(out)


def test_several_locations_without_default_requests_more_evidence(fake, db):
    fake.variants["TT-001"]["levels"]["999"] = dict(fake.variants["TT-001"]["levels"]["456"], name="Warehouse B")
    out = OrderService(db).place_order(order())
    assert out["decision"] == "request_more_evidence" and "location_resolved" in names(out)


def test_default_location_resolves_ambiguity(fake, db, monkeypatch):
    fake.variants["TT-001"]["levels"]["999"] = dict(fake.variants["TT-001"]["levels"]["456"], name="Warehouse B", available=0, on_hand=0)
    monkeypatch.setenv("SHOPIFY_DEFAULT_LOCATION_ID", "456")
    assert OrderService(db).place_order(order())["decision"] == "allow"


@pytest.mark.parametrize("bad", [
    {"items": []}, {"items": [{"sku": "bad sku!", "quantity": 1}]},
    {"items": [{"sku": "TT-001", "quantity": 0}]}, {"items": [{"sku": "TT-001", "quantity": 99}]},
    {"items": [{"sku": "TT-001", "quantity": True}]},
    {"items": [{"sku": "TT-001", "quantity": 1}, {"sku": "tt-001", "quantity": 1}]},
    {"customer": {"name": "", "email": "x@example.com"}}, {"customer": {"name": "A", "email": "not-an-email"}},
    {"idempotency_key": "short"}, {"observed_at": "yesterday-ish"}])
def test_bad_input_is_blocked_before_any_shopify_call(fake, db, bad):
    out = OrderService(db).place_order(order(**bad))
    assert out["decision"] == "block" and "schema" in names(out)
    assert not fake.calls


def test_orders_disabled_verifies_but_creates_nothing(fake, db, monkeypatch):
    monkeypatch.setenv("SHOPIFY_ORDERS_ENABLED", "false")
    out = OrderService(db).place_order(order())
    assert out["decision"] == "allow" and out["status"] == "verified_not_executed"
    assert "turned off" in out["reason"] and "create" not in fake.calls


def test_missing_write_scope_fails_before_any_mutation(fake, db):
    fake.scopes = "read_products,read_inventory,read_locations"
    out = OrderService(db).place_order(order())
    assert out["decision"] == "allow" and out["status"] == "execution_failed"
    assert "write_draft_orders" in out["reason"] and "create" not in fake.calls


def test_shopify_rejecting_the_draft_is_reported_not_hidden(fake, db):
    fake.create_mode = "user_error"
    out = OrderService(db).place_order(order())
    assert out["status"] == "execution_failed" and "Boom" in out["reason"] and not fake.orders


def test_complete_failure_leaves_no_order(fake, db):
    fake.complete_mode = "user_error"
    out = OrderService(db).place_order(order())
    assert out["status"] == "execution_failed" and "could not be completed" in out["reason"] and not fake.orders


def test_shopify_down_during_verification_requests_more_evidence(fake, db):
    set_client(ShopifyClient(SETTINGS, transport=httpx.MockTransport(lambda r: httpx.Response(500) if "graphql" in r.url.path
                                                                      else httpx.Response(200, json={"access_token": "t", "scope": ALL_SCOPES})),
                             sleep=lambda s: None))
    out = OrderService(db).place_order(order())
    assert out["decision"] == "request_more_evidence" and "source_available" in names(out)


def test_readback_mismatch_is_flagged_not_called_verified(fake, db):
    fake.readback = "mismatch"
    out = OrderService(db).place_order(order())
    assert out["status"] == "executed_unverified" and "does not match" in out["reason"]
    assert out["order"]["name"] == "#1001"


def test_readback_denied_is_unverified(fake, db):
    fake.readback = "denied"
    out = OrderService(db).place_order(order())
    assert out["status"] == "executed_unverified" and "Could not read the order back" in out["reason"]


def test_draft_mode_creates_and_proves_a_draft_only(fake, db, monkeypatch):
    monkeypatch.setenv("SHOPIFY_ORDER_MODE", "draft")
    out = OrderService(db).place_order(order())
    assert out["status"] == "executed_verified" and "complete" not in fake.calls and not fake.orders and len(fake.drafts) == 1


# ---- timeouts: never retry blindly
def test_timeout_after_create_finds_the_draft_and_carries_on(fake, db):
    fake.create_mode = "timeout_after_create"
    out = OrderService(db).place_order(order())
    assert out["status"] == "executed_verified" and fake.calls.count("create") == 1 and len(fake.drafts) == 1 and len(fake.orders) == 1


def test_timeout_before_create_is_uncertain_and_not_retried(fake, db):
    fake.create_mode = "timeout_before_create"
    out = OrderService(db).place_order(order())
    assert out["status"] == "uncertain" and fake.calls.count("create") == 1 and not fake.drafts
    # later, same key: Shopify still has nothing, still no blind retry
    again = OrderService(db).place_order(order())
    assert again["status"] == "uncertain" and fake.calls.count("create") == 1


def test_timeout_after_complete_is_resolved_by_lookup(fake, db):
    fake.complete_mode = "timeout_after"
    out = OrderService(db).place_order(order())
    assert out["status"] == "executed_verified" and len(fake.orders) == 1 and fake.calls.count("complete") == 1


def test_uncertain_attempt_resolves_when_the_record_shows_up(fake, db):
    fake.create_mode, fake.tag_search = "timeout_after_create", False       # created, but search can't see it yet
    out = OrderService(db).place_order(order())
    assert out["status"] == "uncertain" and len(fake.drafts) == 1 and not fake.orders
    fake.tag_search = True                                                  # search index caught up
    again = OrderService(db).place_order(order())
    assert again["status"] == "executed_verified" and len(fake.orders) == 1 and fake.calls.count("create") == 1


def test_mutations_are_not_retried_by_the_client(fake):
    from integrations.shopify.errors import ShopifyUnavailableError
    c = ShopifyClient(SETTINGS, transport=httpx.MockTransport(lambda r: httpx.Response(502) if "graphql" in r.url.path
                                                              else httpx.Response(200, json={"access_token": "t", "scope": ""})),
                      sleep=lambda s: None)
    hits = []
    orig = c._http.post
    c._http.post = lambda *a, **k: (hits.append(1), orig(*a, **k))[1]
    with pytest.raises(ShopifyUnavailableError):
        c.graphql("mutation { x }", mutation=True)
    assert len(hits) == 2          # 1 token request + exactly 1 graphql attempt


# ============================================================ catalog
def test_catalog_paginates_and_hides_inactive(fake, api):
    for i in range(30):
        fake.add(f"BULK-{i}", stock=3, title=f"Bulk {i}")
    fake.add("TT-HIDDEN", status="ARCHIVED")
    fake.add("TT-OUT", stock=0)
    fake.add("TT-NOTRACK", tracked=False)
    r = api.get("/shop/catalog")
    assert r.status_code == 200
    body = r.json()
    skus = {v["sku"]: v for p in body["products"] for v in p["variants"]}
    assert len(skus) == 2 + 30 + 2 and "TT-HIDDEN" not in skus          # > one page of 25, so pagination worked
    assert skus["TT-001"]["purchasable"] and skus["TT-001"]["available"] == 10 and skus["TT-001"]["max_quantity"] == 10
    assert skus["TT-OUT"]["status"] == "out_of_stock" and not skus["TT-OUT"]["purchasable"]
    assert skus["TT-NOTRACK"]["status"] == "untracked" and not skus["TT-NOTRACK"]["purchasable"]
    assert body["currency"] == "INR" and body["orders_enabled"] is True
    assert SECRET not in r.text


def test_catalog_without_shopify_configured_is_503(api, monkeypatch):
    monkeypatch.delenv("SHOPIFY_STORE_DOMAIN")
    assert api.get("/shop/catalog").status_code == 503


# ============================================================ HTTP API
def test_api_order_roundtrip_and_public_result(fake, api):
    r = api.post("/shop/orders", json=order(key="api-key-000001"))
    assert r.status_code == 200 and r.json()["decision_label"] == "ALLOW"
    run = r.json()["run_id"]
    got = api.get(f"/shop/orders/{run}")
    assert got.status_code == 200 and got.json()["order"]["name"] == "#1001"
    assert "demo@example.com" not in got.text and got.json()["customer"]["email_masked"] == "d***@example.com"
    assert api.get("/shop/orders/doesnotexist").status_code == 404


def test_api_duplicate_key_returns_same_order(fake, api):
    a = api.post("/shop/orders", json=order(key="api-key-dup0001")).json()
    b = api.post("/shop/orders", json=order(key="api-key-dup0001")).json()
    assert a["run_id"] == b["run_id"] and b["replayed"] and len(fake.orders) == 1


def test_api_conflicting_key_is_409(fake, api):
    api.post("/shop/orders", json=order(key="api-key-conf001"))
    r = api.post("/shop/orders", json=order(key="api-key-conf001", items=[{"sku": "TT-001", "quantity": 4}]))
    assert r.status_code == 409 and r.json()["decision"] == "block"


def test_api_rate_limit(fake, api):
    shop_router.order_limiter.limit = 2
    codes = [api.post("/shop/orders", json=order(key=f"api-rate-{i:05d}")).status_code for i in range(4)]
    assert codes[:2] == [200, 200] and codes[2:] == [429, 429]


def test_api_rejects_oversized_body(fake, api):
    r = api.post("/shop/orders", json=order(items=[{"sku": "TT-001", "quantity": 1, "pad": "x" * 20000}]))
    assert r.status_code == 400


def test_admin_monitor_needs_login_and_reports(fake, api, admin_headers):
    assert api.get("/shop/admin/orders").status_code in (401, 403)
    assert api.get("/shop/admin/monitor").status_code in (401, 403)
    api.post("/shop/orders", json=order(key="api-mon-000001"))
    api.post("/shop/orders", json=order(key="api-mon-000002", items=[{"sku": "NOPE", "quantity": 1}]))
    mon = api.get("/shop/admin/monitor", headers=admin_headers).json()
    assert mon["connection"]["ok"] and mon["connection"]["missing_order_scopes"] == []
    assert mon["attempts_by_status"] == {"executed_verified": 1, "rejected": 1}
    assert mon["decisions_last_24h"] == {"allow": 1, "block": 1} and mon["needs_attention"] == 0
    rows = api.get("/shop/admin/orders", headers=admin_headers).json()
    assert len(rows) == 2 and rows[1]["order_name"] == "#1001"


def test_order_evidence_is_private_but_available_to_admin(fake, api, admin_headers):
    run = api.post("/shop/orders", json=order(key="api-evid-000001")).json()
    eid = run["order_entity_id"]
    assert api.get(f"/gateway/evidence/{eid}").status_code in (401, 403)       # shopify evidence is admin-only
    nodes = api.get(f"/gateway/evidence/{eid}", headers=admin_headers).json()
    assert "decision=allow" in {n["claim"] for n in nodes["nodes"]}
    # the decision is linked back to the stock observation that justified it (stored; the explorer
    # only draws edges whose two ends share one entity, so check the table directly)
    from gateway.models import EvidenceEdge
    d = SessionLocal()
    try:
        edge = d.query(EvidenceEdge).filter_by(relation_type="supports").one()
        assert d.get(EvidenceNode, edge.from_node_id).claim == "quantity_available=10"
        assert d.get(EvidenceNode, edge.to_node_id).entity_id == eid
    finally:
        d.close()


def test_shopify_status_reports_order_scopes(fake, api, admin_headers):
    s = api.get("/shopify/status", headers=admin_headers).json()
    assert s["orders_enabled"] is True and s["read_only"] is False and s["connection"]["missing_order_scopes"] == []
