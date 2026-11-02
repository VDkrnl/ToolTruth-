"""Fetch one SKU's inventory from Shopify and turn it into ToolTruth's common shape."""
import re
from datetime import datetime, timezone

from engine.consistency import LOCATION_PATTERN, SKU_PATTERN
from .errors import InventoryLookupError
from .queries import INVENTORY_BY_SKU, QUANTITY_NAMES

# Sum rule from Shopify docs: on_hand = available + committed + reserved
#                                       + damaged + safety_stock + quality_control
ON_HAND_COMPONENTS = ["available", "committed", "reserved", "damaged", "safety_stock", "quality_control"]


def numeric_id(value) -> str:
    "'gid://shopify/Location/456' -> '456'  (also accepts '456')."
    text = str(value or "").split("?")[0]
    return text.rsplit("/", 1)[-1]


def location_gid(value) -> str:
    return f"gid://shopify/Location/{numeric_id(value)}"


def parse_iso(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def to_naive_utc(dt: datetime | None) -> datetime | None:
    """Database columns store UTC without a timezone label."""
    if dt is None:
        return None
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)).replace(tzinfo=None)


def build_entity_id(sku: str, location_numeric: str) -> str:
    return f"shopify:{sku}:{location_numeric}"


def fetch_inventory(client, sku: str, location_id: str | None = None,
                    default_location_id: str = "", now: datetime | None = None) -> dict:
    """Returns the normalised observation, or raises InventoryLookupError."""
    if not SKU_PATTERN.match(sku or ""):
        raise InventoryLookupError("invalid_sku", "SKU contains unsupported characters.")
    if location_id and not LOCATION_PATTERN.match(str(location_id)):
        raise InventoryLookupError("invalid_location", "location_id must be a number or a Shopify Location ID.")

    data = client.graphql(INVENTORY_BY_SKU, {"query": f'sku:"{sku}"'})
    fetched_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    nodes = [e["node"] for e in (data.get("inventoryItems") or {}).get("edges", []) if e.get("node")]
    # Shopify's search is fuzzy; keep only exact (case-insensitive) SKU matches.
    matches = [n for n in nodes if (n.get("sku") or "").strip().casefold() == sku.casefold()]
    if not matches:
        raise InventoryLookupError("sku_not_found", f"No inventory item with SKU '{sku}' exists in this Shopify store.")
    if len(matches) > 1:
        raise InventoryLookupError(
            "ambiguous_sku", f"SKU '{sku}' matches {len(matches)} inventory items; SKUs must be unique to verify safely.",
            {"inventory_item_ids": [m.get("id") for m in matches]})
    item = matches[0]

    levels = [e["node"] for e in (item.get("inventoryLevels") or {}).get("edges", []) if e.get("node")]
    if not item.get("tracked") or not levels:
        raise InventoryLookupError(
            "inventory_not_tracked",
            f"SKU '{item.get('sku')}' has no tracked stock at any location (turn on 'Track quantity' in Shopify).")

    options = [{"location_id": numeric_id(l["location"]["id"]), "location_name": l["location"].get("name")}
               for l in levels]
    wanted = numeric_id(location_id) if location_id else numeric_id(default_location_id)
    if wanted:
        chosen = [l for l in levels if numeric_id(l["location"]["id"]) == wanted]
        if not chosen:
            raise InventoryLookupError("location_not_found",
                                       f"SKU '{item.get('sku')}' is not stocked at location {wanted}.",
                                       {"locations": options})
        level = chosen[0]
    elif len(levels) == 1:
        level = levels[0]
    else:
        raise InventoryLookupError("ambiguous_location",
                                   "This SKU is stocked at several locations; pass location_id.",
                                   {"locations": options})

    quantities, updated = {}, {}
    for q in level.get("quantities") or []:
        if q.get("name") in QUANTITY_NAMES and isinstance(q.get("quantity"), int):
            quantities[q["name"]] = q["quantity"]
            updated[q["name"]] = q.get("updatedAt")
    if "available" not in quantities:
        raise InventoryLookupError("no_available_quantity", "Shopify did not return an 'available' quantity.")

    source_updated = parse_iso(updated.get("available")) or parse_iso(level.get("updatedAt"))
    variant = item.get("variant") or {}
    try:
        price = float(variant.get("price")) if variant.get("price") is not None else None
    except (TypeError, ValueError):
        price = None
    loc_numeric = numeric_id(level["location"]["id"])

    return {
        "provider": "shopify",
        "source": "shopify",
        "sku": item["sku"],
        "product_id": variant.get("id"),
        "product_title": (variant.get("product") or {}).get("title"),
        "inventory_item_id": item["id"],
        "inventory_item_numeric_id": numeric_id(item["id"]),
        "location_id": level["location"]["id"],
        "location_numeric_id": loc_numeric,
        "location_name": level["location"].get("name"),
        "price": price,
        "quantities": quantities,
        "quantity_updated_at": updated,
        "source_updated_at": source_updated.isoformat() if source_updated else None,
        "fetched_at": fetched_at.isoformat(),
        "entity_id": build_entity_id(item["sku"], loc_numeric),
    }


def flat_claim_fields(obs: dict) -> dict:
    """The scalar facts that become evidence claims (same names the simulator uses)."""
    q = obs["quantities"]
    flat = {"sku": obs["sku"], "quantity_available": q["available"]}
    for name in ("on_hand", "committed", "reserved", "damaged", "safety_stock", "quality_control", "incoming"):
        if name in q:
            flat[name] = q[name]
    if obs.get("price") is not None:
        flat["price"] = obs["price"]
    flat["as_of_timestamp"] = obs["fetched_at"]
    return flat
