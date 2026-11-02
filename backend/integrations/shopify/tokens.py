"""Gets and renews the 24-hour Shopify access token (client credentials grant)."""
import threading
import time

import httpx

from .config import ShopifySettings
from .errors import ShopifyAuthError, ShopifyNotConfiguredError, ShopifyUnavailableError


class ShopifyTokenManager:
    REFRESH_MARGIN_SECONDS = 60

    def __init__(self, settings: ShopifySettings, http: httpx.Client, clock=time.time):
        self._settings = settings
        self._http = http
        self._clock = clock
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at = 0.0
        self.scopes: list[str] = []

    def get_token(self, force_refresh: bool = False) -> str:
        with self._lock:
            now = self._clock()
            if (not force_refresh and self._token
                    and now < self._expires_at - self.REFRESH_MARGIN_SECONDS):
                return self._token
            if not self._settings.configured:
                raise ShopifyNotConfiguredError(
                    "Shopify is not configured. Set SHOPIFY_STORE_DOMAIN, SHOPIFY_CLIENT_ID "
                    "and SHOPIFY_CLIENT_SECRET.")
            try:
                resp = self._http.post(
                    self._settings.token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._settings.client_id,
                        "client_secret": self._settings.client_secret,
                    },
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise ShopifyUnavailableError(
                    f"Could not reach Shopify's token endpoint ({type(exc).__name__}).") from None
            if resp.status_code != 200:
                raise ShopifyAuthError(
                    f"Shopify rejected the token request (HTTP {resp.status_code}): "
                    f"{self._safe_error(resp)}")
            try:
                body = resp.json()
            except ValueError:
                raise ShopifyAuthError("Shopify's token response was not valid JSON.") from None
            token = body.get("access_token")
            if not isinstance(token, str) or not token:
                raise ShopifyAuthError("Shopify's token response did not contain an access_token.")
            try:
                expires_in = int(body.get("expires_in", 86399))
            except (TypeError, ValueError):
                expires_in = 86399
            self._token = token
            self._expires_at = now + expires_in
            scope = body.get("scope") or ""
            self.scopes = [s.strip() for s in str(scope).split(",") if s.strip()]
            return token

    def invalidate(self) -> None:
        with self._lock:
            self._token = None
            self._expires_at = 0.0

    @staticmethod
    def _safe_error(resp: httpx.Response) -> str:
        """Only quotes Shopify's own 'error' fields, never anything we sent."""
        try:
            body = resp.json()
            parts = [str(body.get(k)) for k in ("error", "error_description") if body.get(k)]
            return "; ".join(parts)[:200] or "no details"
        except Exception:
            return "no details"
