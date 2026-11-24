"""Admin-only Shopify connection status endpoint."""
from fastapi import APIRouter, Depends

from auth import current_admin
from integrations.shopify import get_client
from integrations.shopify.config import ORDER_SCOPES, REQUIRED_SCOPES, load_settings
from integrations.shopify.errors import ShopifyError
from integrations.shopify.queries import SHOP_INFO

router = APIRouter(prefix="/shopify", tags=["shopify"])


@router.get("/status")
def status(_=Depends(current_admin)):
    """Return the current Shopify connection status (admin only)."""
    s = load_settings()
    out = {
        "configured": s.configured,
        "store_domain": s.store_domain or None,
        "api_version": s.api_version,
        "orders_enabled": s.orders_enabled,
        "order_mode": s.order_mode,
        "read_only": not s.orders_enabled,
    }
    if s.configured:
        try:
            client = get_client()
            shop = client.graphql(SHOP_INFO).get("shop") or {}
            granted = list(client.tokens.scopes)
            out["connection"] = {
                "ok": True,
                "shop_name": shop.get("name"),
                "scopes": granted,
                "missing_read_scopes": [x for x in REQUIRED_SCOPES if x not in granted],
                "missing_order_scopes": [x for x in ORDER_SCOPES if x not in granted],
            }
        except ShopifyError as exc:
            out["connection"] = {"ok": False, "error": str(exc)}
    return out
