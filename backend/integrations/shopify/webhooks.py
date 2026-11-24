"""Receives Shopify 'inventory_levels/update' webhooks safely.

Rules (from Shopify's docs):
  * verify X-Shopify-Hmac-Sha256 over the RAW body with the app's client secret
  * answer within 5 seconds (we only do small database work)
  * the same event can arrive twice (dedupe on X-Shopify-Event-Id)
  * events can arrive out of order (compare X-Shopify-Triggered-At)
"""
import base64
import hashlib
import hmac
import json

from sqlalchemy.exc import IntegrityError

from database import SessionLocal
from gateway.models import EvidenceEdge, EvidenceNode, ShopifyWebhookEvent
from .config import ShopifySettings, normalize_store_domain
from .inventory import parse_iso, to_naive_utc

SUPPORTED_TOPIC = "inventory_levels/update"
MAX_BODY_BYTES = 256 * 1024


def verify_hmac(raw_body: bytes, signature: str, secret: str) -> bool:
    if not signature or not secret:
        return False
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest)
    return hmac.compare_digest(expected, signature.strip().encode("utf-8", "ignore"))


def process_inventory_webhook(raw_body: bytes, headers: dict, settings: ShopifySettings) -> dict:
    """`headers` must have lower-case keys. Returns a small status dict (always HTTP 200)."""
    topic = headers.get("x-shopify-topic", "")
    if topic != SUPPORTED_TOPIC:
        return {"status": "ignored", "reason": f"unsupported topic '{topic}'"}
    if normalize_store_domain(headers.get("x-shopify-shop-domain", "")) != settings.store_domain:
        return {"status": "ignored", "reason": "webhook is from a different shop"}
    try:
        payload = json.loads(raw_body.decode("utf-8"))
        item = str(int(payload["inventory_item_id"]))
        location = str(int(payload["location_id"]))
        available = payload.get("available")
        available = int(available) if available is not None else None
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return {"status": "ignored", "reason": "malformed payload"}

    event_id = (headers.get("x-shopify-event-id") or headers.get("x-shopify-webhook-id")
                or hashlib.sha256(raw_body).hexdigest())[:120]
    source_updated = to_naive_utc(parse_iso(payload.get("updated_at")))
    triggered = to_naive_utc(parse_iso(headers.get("x-shopify-triggered-at"))) or source_updated

    db = SessionLocal()
    try:
        if db.query(ShopifyWebhookEvent).filter_by(event_id=event_id).first():
            return {"status": "duplicate", "event_id": event_id}

        newest = (db.query(ShopifyWebhookEvent)
                  .filter(ShopifyWebhookEvent.inventory_item_id == item,
                          ShopifyWebhookEvent.location_id == location,
                          ShopifyWebhookEvent.status == "processed",
                          ShopifyWebhookEvent.triggered_at.isnot(None))
                  .order_by(ShopifyWebhookEvent.triggered_at.desc()).first())
        is_stale = bool(newest and triggered and triggered < newest.triggered_at)

        known = (db.query(EvidenceNode)
                 .filter(EvidenceNode.provider == "shopify", EvidenceNode.resource_id == item,
                         EvidenceNode.location_id == location)
                 .order_by(EvidenceNode.id.desc()).first())
        entity_id = known.entity_id if known else f"shopify:item-{item}:{location}"

        row = ShopifyWebhookEvent(
            event_id=event_id, topic=topic, shop_domain=settings.store_domain,
            inventory_item_id=item, location_id=location, available=available,
            triggered_at=triggered, source_updated_at=source_updated,
            status="stale_ignored" if is_stale else "processed", entity_id=entity_id)
        db.add(row)
        try:
            db.flush()
        except IntegrityError:        # two copies of the same event arrived at once
            db.rollback()
            return {"status": "duplicate", "event_id": event_id}

        if not is_stale and available is not None:
            claim = f"quantity_available={available}"
            node = EvidenceNode(
                node_type="claim", entity_id=entity_id, claim=claim, source="shopify_webhook",
                confidence="1.0", schema_version="1.0", timestamp=triggered or source_updated,
                provider="shopify", resource_id=item, location_id=location,
                source_updated_at=source_updated, fetched_at=row.received_at)
            db.add(node)
            db.flush()
            before = (db.query(EvidenceNode)
                      .filter(EvidenceNode.entity_id == entity_id, EvidenceNode.provider == "shopify",
                              EvidenceNode.claim.like("quantity_available=%"), EvidenceNode.id != node.id)
                      .order_by(EvidenceNode.id.desc()).first())
            if before:
                db.add(EvidenceEdge(from_node_id=before.id, to_node_id=node.id, relation_type="supercedes"))
        db.commit()
        return {"status": row.status, "event_id": event_id, "entity_id": entity_id}
    finally:
        db.close()
