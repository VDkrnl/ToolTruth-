"""Reads Shopify settings from environment variables (never from code)."""
import os
import re
from dataclasses import dataclass

_SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")
_VERSION_RE = re.compile(r"^\d{4}-(01|04|07|10)$")

# Scopes needed to read the catalog and inventory.
REQUIRED_SCOPES = ["read_products", "read_inventory", "read_locations"]
# Extra scopes needed to create (and later prove) orders. Only checked when orders are enabled.
ORDER_SCOPES = ["write_draft_orders", "read_draft_orders", "read_orders"]

ORDER_MODES = ("complete", "draft")   # complete = draft order -> completed order (payment pending)


def normalize_store_domain(raw: str) -> str:
    "'https://My-Store.myshopify.com/' -> 'my-store.myshopify.com'."
    value = (raw or "").strip().lower()
    value = re.sub(r"^https?://", "", value).split("/")[0]
    if value and "." not in value:
        value = f"{value}.myshopify.com"
    return value


@dataclass(frozen=True)
class ShopifySettings:
    store_domain: str = ""
    client_id: str = ""
    client_secret: str = ""
    api_version: str = "2026-10"
    default_location_id: str = ""
    timeout_seconds: float = 10.0
    # Order creation is OFF unless explicitly enabled (SHOPIFY_ORDERS_ENABLED=true).
    orders_enabled: bool = False
    order_mode: str = "complete"

    @property
    def configured(self) -> bool:
        return bool(
            self.client_id
            and self.client_secret
            and _SHOP_RE.match(self.store_domain)
            and _VERSION_RE.match(self.api_version)
        )

    @property
    def token_url(self) -> str:
        return f"https://{self.store_domain}/admin/oauth/access_token"

    @property
    def graphql_url(self) -> str:
        return f"https://{self.store_domain}/admin/api/{self.api_version}/graphql.json"


def _truthy(raw: str) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def load_settings() -> ShopifySettings:
    """Read the environment on every call so changes (and tests) take effect."""
    return ShopifySettings(
        store_domain=normalize_store_domain(os.getenv("SHOPIFY_STORE_DOMAIN", "")),
        client_id=os.getenv("SHOPIFY_CLIENT_ID", "").strip(),
        client_secret=os.getenv("SHOPIFY_CLIENT_SECRET", "").strip(),
        api_version=os.getenv("SHOPIFY_API_VERSION", "2026-10").strip() or "2026-10",
        default_location_id=os.getenv("SHOPIFY_DEFAULT_LOCATION_ID", "").strip(),
        orders_enabled=_truthy(os.getenv("SHOPIFY_ORDERS_ENABLED", "")),
        order_mode=(os.getenv("SHOPIFY_ORDER_MODE", "complete").strip().lower()
                    if os.getenv("SHOPIFY_ORDER_MODE", "complete").strip().lower() in ORDER_MODES
                    else "complete"),
    )
