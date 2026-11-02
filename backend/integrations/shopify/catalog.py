"""Products, variants and per-location stock, read live from Shopify (never hard-coded)."""
from datetime import datetime, timezone

from engine.consistency import SKU_PATTERN
from .inventory import numeric_id, parse_iso
from .queries import CATALOG_PAGE, QUANTITY_NAMES

PAGE_SIZE = 25
MAX_PAGES = 20            # hard ceiling: 500 variants, so a huge store cannot stall the demo


def parse_variant(node: dict) -> dict:
    """Shopify variant node -> plain dict with every location's quantities."""
    item = node.get("inventoryItem") or {}
    product = node.get("product") or {}
    levels = []
    for edge in (item.get("inventoryLevels") or {}).get("edges", []):
        lv = edge.get("node") or {}
        quantities, updated = {}, {}
        for q in lv.get("quantities") or []:
            if q.get("name") in QUANTITY_NAMES and isinstance(q.get("quantity"), int):
                quantities[q["name"]] = q["quantity"]
                updated[q["name"]] = q.get("updatedAt")
        loc = lv.get("location") or {}
        source_updated = parse_iso(updated.get("available")) or parse_iso(lv.get("updatedAt"))
        levels.append({
            "location_id": numeric_id(loc.get("id")),
            "location_name": loc.get("name"),
            "quantities": quantities,
            "source_updated_at": source_updated.isoformat() if source_updated else None,
        })
    try:
        price = float(node["price"]) if node.get("price") is not None else None
    except (TypeError, ValueError):
        price = None
    image = (node.get("image") or {}).get("url") or (product.get("featuredImage") or {}).get("url")
    return {
        "variant_id": node.get("id"),
        "sku": (node.get("sku") or "").strip(),
        "variant_title": node.get("title"),
        "price": price,
        "image_url": image,
        "product_id": product.get("id"),
        "product_title": product.get("title"),
        "product_status": (product.get("status") or "").upper(),
        "inventory_item_id": item.get("id"),
        "inventory_item_numeric_id": numeric_id(item.get("id")),
        "tracked": bool(item.get("tracked")),
        "levels": levels,
    }


def resolve_level(variant: dict, default_location_id: str = "") -> tuple[dict | None, str | None, str]:
    """Which location's stock counts? Returns (level, problem_code, explanation)."""
    levels = variant["levels"]
    if not variant["tracked"]:
        return None, "inventory_not_tracked", "Stock is not tracked for this item, so it cannot be verified."
    if not levels:
        return None, "inventory_not_tracked", "No stocked location found for this item."
    wanted = numeric_id(default_location_id)
    if wanted:
        chosen = [l for l in levels if l["location_id"] == wanted]
        if not chosen:
            return None, "location_not_found", f"Item is not stocked at the configured location {wanted}."
        level = chosen[0]
    elif len(levels) == 1:
        level = levels[0]
    else:
        return None, "ambiguous_location", ("Item is stocked at several locations; set "
                                           "SHOPIFY_DEFAULT_LOCATION_ID so one can be verified.")
    if "available" not in level["quantities"]:
        return None, "no_available_quantity", "Shopify did not return an 'available' quantity."
    return level, None, ""


def _paged(client, query_string: str | None):
    after, currency = None, None
    for _ in range(MAX_PAGES):
        data = client.graphql(CATALOG_PAGE, {"first": PAGE_SIZE, "after": after, "query": query_string})
        currency = currency or (data.get("shop") or {}).get("currencyCode")
        conn = data.get("productVariants") or {}
        for edge in conn.get("edges", []):
            if edge.get("node"):
                yield parse_variant(edge["node"]), currency
        info = conn.get("pageInfo") or {}
        if not info.get("hasNextPage") or not info.get("endCursor"):
            return
        after = info["endCursor"]


def fetch_all_variants(client) -> tuple[list[dict], str | None, datetime]:
    """Every variant in the store (paginated). Returns (variants, currency, fetched_at)."""
    out, currency = [], None
    for v, cur in _paged(client, None):
        out.append(v)
        currency = currency or cur
    return out, currency, datetime.now(timezone.utc)


def fetch_variants_by_sku(client, skus: list[str]) -> tuple[dict[str, list[dict]], datetime]:
    """Fresh data for exactly these SKUs. Result maps lower-cased SKU -> every exact match
    (Shopify search is fuzzy, so non-exact hits are dropped; more than one match = ambiguous)."""
    clean = []
    for s in skus:
        if not SKU_PATTERN.match(s or ""):
            raise ValueError(f"Unsafe SKU: {s!r}")
        if s not in clean:
            clean.append(s)
    found: dict[str, list[dict]] = {}
    fetched_at = datetime.now(timezone.utc)
    for i in range(0, len(clean), 10):
        chunk = clean[i:i + 10]
        query = " OR ".join(f'sku:"{s}"' for s in chunk)
        for v, _cur in _paged(client, query):
            found.setdefault(v["sku"].casefold(), []).append(v)
        fetched_at = datetime.now(timezone.utc)
    wanted = {s.casefold() for s in clean}
    return {k: v for k, v in found.items() if k in wanted}, fetched_at
