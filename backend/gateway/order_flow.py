"""Verify-and-execute flow for customer orders on a live Shopify store.

The BACKEND runs the whole sequence, so a browser cannot skip the verification step:

  schema -> fresh Shopify read -> checks -> evidence saved -> decision
         -> (only if ALLOW and orders are enabled) draft order -> completed order -> read-back proof

Decisions come from the same ConsistencyEngine.produce_decision() used everywhere else.
Safety rules:
  * one idempotency key = at most one Shopify order (unique DB column + stored result is replayed)
  * verify+execute runs under a process-wide lock, so two customers cannot both take the last unit
  * a timeout never triggers a blind retry: the tagged record is looked up in Shopify first
"""
import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from domains.ecommerce import EcommerceDomain
from engine.consistency import SKU_PATTERN, ConsistencyEngine
from engine.schemas import CheckResult
from gateway.live import LiveShopifyHandler
from gateway.models import EvidenceEdge, EvidenceNode, EventLog, OrderAttempt
from integrations.shopify import get_client
from integrations.shopify.catalog import fetch_variants_by_sku, resolve_level
from integrations.shopify.config import ORDER_SCOPES, load_settings
from integrations.shopify.errors import OrderExecutionError, ShopifyError, ShopifyUnavailableError
from integrations.shopify.inventory import build_entity_id, flat_claim_fields, parse_iso, to_naive_utc
from integrations.shopify.orders import (complete_draft_order, create_draft_order, find_by_tag,
                                         idempotency_tag, verify_draft, verify_order)

MAX_LINES = 10
MAX_QTY = 10
DEFAULT_MAX_AGE = 300
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")
IN_FLIGHT_SECONDS = 60       # a "verifying/executing" row younger than this belongs to a live request
LOCK_WAIT_SECONDS = 25

# One verify+execute at a time per server process. Run a single uvicorn worker (see DEPLOY.md);
# with several workers, Shopify itself still refuses to over-commit, and read-back proves the result.
_ORDER_LOCK = threading.Lock()

# Failing any of these asks for more evidence instead of blocking (mirrors ConsistencyEngine.produce_decision).
EVIDENCE_CHECKS = {"user_constraints", "freshness", "source_available", "source_consistency", "location_resolved"}
DECISION_LABELS = {"allow": "ALLOW", "block": "BLOCK", "request_more_evidence": "REQUEST MORE EVIDENCE"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _mask_email(email: str) -> str:
    name, _, domain = (email or "").partition("@")
    return (name[:1] + "***@" + domain) if domain else ""


class OrderService:
    provider = "shopify"

    def __init__(self, db: Session, client=None, settings=None):
        self.db = db
        self._client = client
        self.settings = settings or load_settings()
        self.engine = ConsistencyEngine(db)
        self.domain = EcommerceDomain()      # only its invariants are used; its fake stock never is
        self._live = LiveShopifyHandler(db, client=object(), settings=self.settings)  # evidence writer

    @property
    def client(self):
        return self._client or get_client()

    # ============================================================ public API
    def place_order(self, req: dict) -> dict:
        """Returns a result dict. `http_status` is a hint for the router (200, 202 or 409)."""
        key = str(req.get("idempotency_key") or "")
        schema, cart, customer = self._check_schema(req)
        digest = self._request_hash(cart, customer, req)
        run_id = uuid.uuid4().hex
        key = key if KEY_RE.match(key) else f"invalid-{run_id}"      # a bad key is never stored or reused
        attempt = OrderAttempt(
            run_id=run_id, idempotency_key=key, request_hash=digest, status="verifying",
            shopify_tag=idempotency_tag(key),
            order_mode=self.settings.order_mode,
            cart_json=json.dumps(cart), customer_json=json.dumps({"name": customer.get("name"),
                                                                  "email_masked": _mask_email(customer.get("email", ""))}))
        self.db.add(attempt)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.query(OrderAttempt).filter_by(idempotency_key=key).first()
            if existing is None:       # unique clash on run_id (practically impossible): ask for a retry
                raise
            return self._replay(existing, digest, req, cart, customer)
        return self._verify_and_execute(attempt, req, schema, cart, customer)

    def get_result(self, run_id: str) -> dict | None:
        attempt = self.db.query(OrderAttempt).filter_by(run_id=run_id).first()
        return self._present(attempt) if attempt else None

    # ============================================================ input checks
    def _check_schema(self, req: dict):
        problems, cart = [], []
        key = str(req.get("idempotency_key") or "")
        if not KEY_RE.match(key):
            problems.append("idempotency_key must be 8-64 characters: letters, digits, '-' or '_'.")
        items = req.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_LINES:
            problems.append(f"items must be a list of 1-{MAX_LINES} cart lines.")
            items = []
        seen = set()
        for i, raw in enumerate(items, 1):
            raw = raw if isinstance(raw, dict) else {}
            sku, qty, seen_qty = raw.get("sku"), raw.get("quantity"), raw.get("observed_available")
            if not isinstance(sku, str) or not SKU_PATTERN.match(sku):
                problems.append(f"line {i}: sku must be 1-64 characters: letters, digits, '.', '_' or '-'.")
                continue
            if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= MAX_QTY:
                problems.append(f"line {i} ({sku}): quantity must be a whole number from 1 to {MAX_QTY}.")
                continue
            if seen_qty is not None and (isinstance(seen_qty, bool) or not isinstance(seen_qty, int) or seen_qty < 0):
                problems.append(f"line {i} ({sku}): observed_available must be a whole number >= 0.")
                continue
            if sku.casefold() in seen:
                problems.append(f"line {i}: SKU {sku} appears twice; combine the quantities into one line.")
                continue
            seen.add(sku.casefold())
            cart.append({"sku": sku, "quantity": qty, "observed_available": seen_qty})
        cust = req.get("customer") if isinstance(req.get("customer"), dict) else {}
        name, email = str(cust.get("name") or "").strip(), str(cust.get("email") or "").strip()
        if not 1 <= len(name) <= 80:
            problems.append("customer.name is required (max 80 characters).")
        if not EMAIL_RE.match(email):
            problems.append("customer.email must be a valid email address.")
        age = req.get("max_age_seconds")
        if age is not None and (isinstance(age, bool) or not isinstance(age, int) or not 1 <= age <= 86400):
            problems.append("max_age_seconds must be a whole number between 1 and 86400.")
        observed = req.get("observed_at")
        if observed not in (None, "") and parse_iso(observed) is None:
            problems.append("observed_at must be an ISO-8601 timestamp.")
        if problems:
            return (CheckResult(name="schema", passed=False, reason=" ".join(problems)[:600]),
                    cart, {"name": name, "email": email})
        return CheckResult(name="schema", passed=True, reason="Cart and customer details are well-formed."), \
            cart, {"name": name, "email": email}

    @staticmethod
    def _request_hash(cart, customer, req) -> str:
        canon = {"items": sorted([[c["sku"].casefold(), c["quantity"]] for c in cart]),
                 "email": (customer.get("email") or "").casefold(),
                 "raw_items": len(req.get("items") or []) if isinstance(req.get("items"), list) else -1}
        return hashlib.sha256(json.dumps(canon, sort_keys=True).encode()).hexdigest()

    # ============================================================ replay of a repeated key
    def _replay(self, existing: OrderAttempt, digest: str, req: dict, cart, customer) -> dict:
        if existing.request_hash != digest:
            out = self._present(existing, replayed=True)
            out.update({
                "http_status": 409, "decision": "block", "decision_label": "BLOCK",
                "reason": "This idempotency key was already used for a different cart. "
                          "Start a new order to get a new key.",
                "checks": [CheckResult(name="idempotency", passed=False,
                                       reason="Same idempotency key, different cart.").model_dump()]})
            return out
        age = (_utcnow() - (existing.updated_at or existing.created_at)).total_seconds()
        if existing.status in ("verifying", "executing") and age < IN_FLIGHT_SECONDS:
            out = self._present(existing, replayed=True)
            out.update({"http_status": 202, "in_progress": True,
                        "reason": "This exact request is still being processed. Check again in a moment."})
            return out
        if existing.status == "verifying":          # crashed before touching Shopify: safe to run again
            schema, cart, customer = self._check_schema(req)
            return self._verify_and_execute(existing, req, schema, cart, customer, replayed=True)
        if existing.status in ("executing", "uncertain"):
            return self._reconcile(existing, req, cart, customer)
        return self._present(existing, replayed=True)       # finished before: same answer, no new order

    # ============================================================ verification
    def _verify_and_execute(self, attempt, req, schema, cart, customer, replayed=False) -> dict:
        checks, lines, evidence_rows = [schema], [], []
        if not schema.passed:
            return self._finish(attempt, checks, lines, [], None, replayed)

        if not _ORDER_LOCK.acquire(timeout=LOCK_WAIT_SECONDS):
            checks.append(CheckResult(name="source_available", passed=False,
                                      reason="The server is busy verifying other orders. Please retry."))
            return self._finish(attempt, checks, lines, [], None, replayed)
        try:
            self._set_status(attempt, "verifying")
            try:
                found, fetched_at = fetch_variants_by_sku(self.client, [c["sku"] for c in cart])
            except ShopifyError as exc:
                checks.append(CheckResult(name="source_available", passed=False,
                                          reason=f"Cannot verify: {exc}"))
                return self._finish(attempt, checks, lines, [], None, replayed)

            max_age = req.get("max_age_seconds") or DEFAULT_MAX_AGE
            observed_at = parse_iso(req.get("observed_at"))
            checks.append(self.engine.check_staleness(fetched_at.isoformat(), max_age))
            checks.append(self._check_snapshot_age(observed_at, max_age))
            verified_lines = []
            for line in cart:
                lc, info, evidence = self._check_line(line, found, fetched_at, observed_at)
                checks.extend(lc)
                lines.append(info)
                evidence_rows.extend(evidence)
                if info["verified"]:
                    verified_lines.append({"variant_id": info["variant_id"], "quantity": line["quantity"]})
            checks.append(CheckResult(name="idempotency", passed=True,
                                      reason="New idempotency key; no earlier order for it."))

            decision = self.engine.produce_decision(checks)
            if decision != "allow":
                return self._finish(attempt, checks, lines, evidence_rows, None, replayed)

            if not self.settings.orders_enabled:
                return self._finish(attempt, checks, lines, evidence_rows,
                                    {"outcome": "disabled",
                                     "message": "Verification passed, but order creation is turned off on this server "
                                                "(SHOPIFY_ORDERS_ENABLED is not 'true'). No order was created."},
                                    replayed)
            self._set_status(attempt, "executing")
            execution = self._execute(attempt, verified_lines, customer["email"], None)
            return self._finish(attempt, checks, lines, evidence_rows, execution, replayed)
        finally:
            _ORDER_LOCK.release()

    @staticmethod
    def _check_snapshot_age(observed_at, max_age) -> CheckResult:
        if observed_at is None:
            return CheckResult(name="freshness", passed=True,
                               reason="No customer snapshot supplied; judged on Shopify data read just now.")
        age = (datetime.now(timezone.utc) - observed_at).total_seconds()
        if age < -60:
            return CheckResult(name="freshness", passed=False, reason="observed_at is in the future.")
        if age > max_age:
            return CheckResult(name="freshness", passed=False,
                               reason=f"The stock you saw is {int(age)}s old; the limit is {max_age}s. "
                                      "Refresh the stock and confirm again.")
        return CheckResult(name="freshness", passed=True,
                           reason=f"Customer's stock snapshot is {max(0, int(age))}s old (limit {max_age}s).")

    def _check_line(self, line, found, fetched_at, observed_at):
        """Checks for one cart line. Returns (checks, display_info, evidence)."""
        sku, qty = line["sku"], line["quantity"]
        info = {"sku": sku, "quantity": qty, "verified": False, "product_title": None, "variant_title": None,
                "available": None, "price": None, "location_name": None, "variant_id": None}
        tag = lambda c: setattr(c, "category", sku) or c          # category carries the SKU for display
        matches = found.get(sku.casefold(), [])
        if not matches:
            return [tag(CheckResult(name="tool_result", passed=False,
                                    reason=f"SKU '{sku}' does not exist in this Shopify store."))], info, []
        if len(matches) > 1:
            return [tag(CheckResult(name="tool_result", passed=False,
                                    reason=f"SKU '{sku}' matches {len(matches)} variants; SKUs must be unique to "
                                           "verify safely."))], info, []
        v = matches[0]
        info.update(product_title=v["product_title"], variant_title=v["variant_title"], price=v["price"],
                    variant_id=v["variant_id"])
        checks = []
        active = v["product_status"] == "ACTIVE"
        checks.append(tag(CheckResult(name="product_active", passed=active,
                                      reason=f"SKU {sku}: product is active." if active else
                                      f"SKU {sku}: product status is {v['product_status'] or 'unknown'}, not ACTIVE.")))
        level, code, why = resolve_level(v, self.settings.default_location_id)
        if code in ("ambiguous_location", "location_not_found"):
            checks.append(tag(CheckResult(name="location_resolved", passed=False, reason=f"SKU {sku}: {why}")))
            return checks, info, []
        if code:
            checks.append(tag(CheckResult(name="tool_result", passed=False, reason=f"SKU {sku}: {why}")))
            return checks, info, []

        q = level["quantities"]
        available = q["available"]
        info.update(available=available, location_name=level["location_name"])
        checks.append(tag(CheckResult(
            name="sufficient_inventory", passed=qty <= available,
            reason=(f"SKU {sku}: {qty} requested, {available} available at {level['location_name']}."
                    if qty <= available else
                    f"SKU {sku}: only {available} available at {level['location_name']}; {qty} requested."))))
        sc = LiveShopifyHandler._check_source_consistency(q)
        checks.append(tag(CheckResult(name=sc.name, passed=sc.passed, reason=f"SKU {sku}: {sc.reason}")))
        inv = self.engine.check_invariants(self.domain, {"quantity_available": available, "price": v["price"] or 0})
        checks.append(tag(CheckResult(name=inv.name, passed=inv.passed, reason=f"SKU {sku}: {inv.reason}")))
        checks.append(tag(self._check_changed(line, level, observed_at)))

        obs = {"sku": v["sku"], "quantities": q, "price": v["price"], "fetched_at": fetched_at.isoformat(),
               "source_updated_at": level["source_updated_at"],
               "inventory_item_numeric_id": v["inventory_item_numeric_id"],
               "location_numeric_id": level["location_id"],
               "entity_id": build_entity_id(v["sku"], level["location_id"])}
        evidence, changes = self._live._record_evidence(obs, flat_claim_fields(obs))
        info["entity_id"] = obs["entity_id"]
        info["changes"] = changes
        info["verified"] = all(c.passed for c in checks)
        return checks, info, evidence

    @staticmethod
    def _check_changed(line, level, observed_at) -> CheckResult:
        sku, seen = line["sku"], line.get("observed_available")
        available = level["quantities"]["available"]
        if seen is not None and seen != available:
            return CheckResult(name="freshness", passed=False,
                               reason=f"SKU {sku}: stock changed from {seen} to {available} after your snapshot. "
                                      "Review the cart and confirm again.")
        changed_at = parse_iso(level["source_updated_at"])
        if observed_at and changed_at and changed_at > observed_at:
            return CheckResult(name="freshness", passed=False,
                               reason=f"SKU {sku}: Shopify changed this stock at {changed_at.isoformat()}, "
                                      f"after your snapshot ({observed_at.isoformat()}).")
        return CheckResult(name="freshness", passed=True,
                           reason=f"SKU {sku}: no change since the snapshot." if seen is not None or observed_at
                           else f"SKU {sku}: read from Shopify just now.")

    # ============================================================ execution
    def _execute(self, attempt, lines, email, resume: dict | None) -> dict:
        """Creates the order and proves it. Never retries a mutation whose outcome is unknown."""
        client, mode, tag = self.client, self.settings.order_mode, attempt.shopify_tag
        ex = {"mode": mode, "draft_id": None, "order_id": None, "order_name": None,
              "verification": None, "outcome": None, "message": ""}
        try:
            token = client.tokens.get_token()                       # also fills client.tokens.scopes
            granted = list(client.tokens.scopes)
            missing = [s for s in ORDER_SCOPES if s not in granted] if granted else []
            if missing and token:
                ex.update(outcome="failed", message="Orders cannot be created: the Shopify app is missing the "
                                                    f"scope(s) {', '.join(missing)}. Add them, release the app "
                                                    "version and re-approve the install.")
                return ex
        except ShopifyError as exc:
            ex.update(outcome="failed", message=f"Cannot reach Shopify to create the order: {exc}")
            return ex

        found = resume
        if found is None:
            try:
                d = create_draft_order(client, lines, email, tag, attempt.run_id)
                ex.update(draft_id=d["id"], order_name=d["name"])
                found = {"draft_id": d["id"], "draft_name": d["name"], "order_id": None, "order_name": None}
            except ShopifyUnavailableError:
                state, rec = self._lookup(tag)
                if state != "found":
                    ex.update(outcome="uncertain", message=self._uncertain_text(state))
                    return ex
                found = rec
            except (OrderExecutionError, ShopifyError) as exc:
                ex.update(outcome="failed", message=f"Shopify did not create the order: {getattr(exc, 'message', exc)}")
                return ex
        ex.update(draft_id=found["draft_id"], order_id=found.get("order_id"), order_name=found.get("order_name") or found.get("draft_name"))

        if mode == "draft":
            ver = verify_draft(client, found["draft_id"], lines)
            return self._conclude(ex, ver)

        if not found.get("order_id"):
            try:
                done = complete_draft_order(client, found["draft_id"])
                ex.update(order_id=done["order_id"], order_name=done["order_name"])
            except ShopifyUnavailableError:
                state, rec = self._lookup(tag)
                if state == "found" and rec.get("order_id"):
                    ex.update(order_id=rec["order_id"], order_name=rec.get("order_name"))
                else:
                    ex.update(outcome="uncertain",
                              message="A draft order exists in Shopify but Shopify did not confirm that it was "
                                      "completed. Nothing was retried. Check Shopify Admin before ordering again.")
                    return ex
            except (OrderExecutionError, ShopifyError) as exc:
                ex.update(outcome="failed",
                          message=f"The draft order was created but could not be completed: "
                                  f"{getattr(exc, 'message', exc)}. No order exists; the draft will lapse.")
                return ex
        ver = verify_order(client, ex["order_id"], lines, tag)
        return self._conclude(ex, ver)

    @staticmethod
    def _conclude(ex: dict, ver: dict) -> dict:
        ex["verification"] = ver
        if ver.get("order_name"):
            ex["order_name"] = ver["order_name"]
        if ver["verified"]:
            ex.update(outcome="verified", message=ver["reason"])
        else:
            ex.update(outcome="unverified", message=ver["reason"])
        return ex

    def _lookup(self, tag: str):
        try:
            rec = find_by_tag(self.client, tag)
        except (ShopifyError, ValueError):
            return "error", None
        return ("found", rec) if rec else ("none", None)

    @staticmethod
    def _uncertain_text(state: str) -> str:
        if state == "error":
            return ("Shopify did not answer and could not be asked again, so the result is unknown. "
                    "Nothing was retried. Check Shopify Admin before ordering again.")
        return ("Shopify did not answer, and no record of this request was found there yet. "
                "Nothing was retried automatically; use the same request key to check again later.")

    def _reconcile(self, attempt, req, cart, customer) -> dict:
        """Same key sent again after an unknown outcome: look in Shopify, never blindly re-create."""
        if not _ORDER_LOCK.acquire(timeout=LOCK_WAIT_SECONDS):
            out = self._present(attempt, replayed=True)
            out.update({"http_status": 202, "in_progress": True, "reason": "Busy. Try again shortly."})
            return out
        try:
            state, rec = self._lookup(attempt.shopify_tag)
            old = json.loads(attempt.execution_json or "{}")
            if state != "found":
                old.update(outcome="uncertain", message=self._uncertain_text(state))
                attempt.status, attempt.execution_json = "uncertain", json.dumps(old)
                attempt.reason, attempt.updated_at = old["message"], _utcnow()
                self.db.commit()
                return self._present(attempt, replayed=True)
            lines = [{"variant_id": l["variant_id"], "quantity": l["quantity"]}
                     for l in json.loads(attempt.lines_json or "[]") if l.get("verified")]
            ex = self._execute(attempt, lines, customer.get("email", ""), rec)
            return self._finish(attempt, [CheckResult(**c) for c in json.loads(attempt.checks_json or "[]")],
                                json.loads(attempt.lines_json or "[]"),
                                json.loads(attempt.evidence_json or "[]"), ex, True)
        finally:
            _ORDER_LOCK.release()

    # ============================================================ persistence / output
    def _set_status(self, attempt, status):
        attempt.status, attempt.updated_at = status, _utcnow()
        self.db.commit()

    def _finish(self, attempt, checks, lines, evidence, execution, replayed) -> dict:
        decision = self.engine.produce_decision(checks)
        failed = [c for c in checks if not c.passed]
        if decision == "block":      # show the failure that actually caused the BLOCK first
            failed.sort(key=lambda c: c.name in EVIDENCE_CHECKS)
        reason = failed[0].reason if failed else "All consistency checks passed."
        status = {"block": "rejected", "request_more_evidence": "needs_evidence"}.get(decision)
        if decision == "allow":
            outcome = (execution or {}).get("outcome")
            status = {"disabled": "verified_not_executed", "verified": "executed_verified",
                      "unverified": "executed_unverified", "failed": "execution_failed",
                      "uncertain": "uncertain"}.get(outcome, "verified_not_executed")
            reason = (execution or {}).get("message") or reason
        attempt.status, attempt.decision, attempt.reason = status, decision, reason
        attempt.checks_json = json.dumps([c.model_dump() for c in checks])
        attempt.lines_json = json.dumps(lines)
        attempt.evidence_json = json.dumps(evidence)
        attempt.execution_json = json.dumps(execution or {})
        if execution:
            attempt.shopify_order_id = execution.get("order_id")
            attempt.shopify_order_name = execution.get("order_name") if execution.get("order_id") else None
        attempt.updated_at = _utcnow()
        self.db.add(EventLog(
            domain="ecommerce", action="place_order",
            payload_json=json.dumps({"provider": "shopify", "run_id": attempt.run_id,
                                     "items": json.loads(attempt.cart_json)}, sort_keys=True, default=str),
            result_json=json.dumps({"status": status, "order": attempt.shopify_order_name}),
            agent_id="shop-customer", status="allowed" if decision == "allow" else "blocked",
            reason=reason, dependencies_json="[]"))
        self.db.commit()
        self._record_decision_evidence(attempt, evidence)
        return self._present(attempt, replayed=replayed)

    def _record_decision_evidence(self, attempt, evidence):
        """Order-level evidence: the decision and (if any) the Shopify order, linked to the stock
        observations that justified it."""
        entity = f"shopify-order:{attempt.run_id}"
        now = _utcnow()
        claims = [f"decision={attempt.decision}", f"order_status={attempt.status}"]
        if attempt.shopify_order_name:
            claims.append(f"shopify_order={attempt.shopify_order_name}")
        ex = json.loads(attempt.execution_json or "{}")
        if ex.get("verification"):
            claims.append(f"order_verified={str(bool(ex['verification'].get('verified'))).lower()}")
        nodes = []
        for claim in claims:
            n = EvidenceNode(node_type="claim", entity_id=entity, claim=claim, source="tooltruth-order-flow",
                             confidence="1.0", schema_version="1.0", timestamp=now, provider="shopify",
                             resource_id=(attempt.shopify_order_id or "").rsplit("/", 1)[-1] or None,
                             fetched_at=now)
            self.db.add(n)
            nodes.append(n)
        self.db.flush()
        if nodes:
            for e in evidence:
                if str(e.get("claim", "")).startswith("quantity_available="):
                    self.db.add(EvidenceEdge(from_node_id=e["id"], to_node_id=nodes[0].id, relation_type="supports"))
        self.db.commit()

    def _present(self, a: OrderAttempt, replayed: bool = False) -> dict:
        ex = json.loads(a.execution_json or "{}")
        decision = a.decision or "request_more_evidence"
        return {
            "http_status": 200,
            "run_id": a.run_id,
            "status": a.status,
            "decision": decision,
            "decision_label": DECISION_LABELS.get(decision, decision),
            "reason": a.reason,
            "in_progress": a.status in ("verifying", "executing"),
            "replayed": replayed,
            "checks": json.loads(a.checks_json or "[]"),
            "lines": [{k: v for k, v in l.items() if k not in ("variant_id",)} for l in json.loads(a.lines_json or "[]")],
            "evidence_trail": json.loads(a.evidence_json or "[]"),
            "order_entity_id": f"shopify-order:{a.run_id}",
            "execution": {k: ex.get(k) for k in ("mode", "outcome", "message", "order_name", "verification")} if ex else {},
            "order": ({"name": a.shopify_order_name, "id": a.shopify_order_id} if a.shopify_order_id else None),
            "customer": json.loads(a.customer_json or "{}"),
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
