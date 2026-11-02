"""Tiny GraphQL client for the Shopify Admin API (sync, retries, no secrets in errors)."""
import logging
import threading
import time

import httpx

from .config import ShopifySettings, load_settings
from .errors import (ShopifyAPIError, ShopifyAuthError, ShopifyNotConfiguredError,
                     ShopifyUnavailableError)
from .tokens import ShopifyTokenManager

log = logging.getLogger("tooltruth.shopify")


class ShopifyClient:
    MAX_ATTEMPTS = 4

    def __init__(self, settings: ShopifySettings | None = None, transport=None,
                 sleep=time.sleep, clock=time.time):
        self.settings = settings or load_settings()
        self._http = httpx.Client(transport=transport, timeout=self.settings.timeout_seconds)
        self.tokens = ShopifyTokenManager(self.settings, self._http, clock)
        self._sleep = sleep
        self.api_version_served: str | None = None

    def graphql(self, query: str, variables: dict | None = None, *, mutation: bool = False) -> dict:
        """mutation=True: a lost response or a 5xx is NOT retried, because Shopify may already have
        done the work. The caller must look the result up before trying again."""
        if not self.settings.configured:
            raise ShopifyNotConfiguredError(
                "Shopify is not configured. Set SHOPIFY_STORE_DOMAIN, SHOPIFY_CLIENT_ID "
                "and SHOPIFY_CLIENT_SECRET.")
        refreshed = False
        last_problem = "unknown problem"
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            token = self.tokens.get_token()
            try:
                resp = self._http.post(
                    self.settings.graphql_url,
                    json={"query": query, "variables": variables or {}},
                    headers={"X-Shopify-Access-Token": token},
                )
            except httpx.HTTPError as exc:
                last_problem = f"network error ({type(exc).__name__})"
                if mutation:
                    raise ShopifyUnavailableError(
                        f"Shopify did not answer ({last_problem}); the outcome is unknown.") from None
                self._sleep(0.5 * attempt)
                continue

            served = resp.headers.get("X-Shopify-API-Version")
            if served:
                self.api_version_served = served
                if served != self.settings.api_version:
                    log.warning("Shopify served API version %s but %s was requested",
                                served, self.settings.api_version)

            if resp.status_code == 401:
                if refreshed:
                    raise ShopifyAuthError("Shopify rejected the access token even after renewing it.")
                self.tokens.invalidate()
                refreshed = True
                continue
            if resp.status_code == 403:
                raise ShopifyAuthError("Shopify refused access (HTTP 403). Check the app's scopes "
                                       "and that the app is installed on the store.")
            if resp.status_code == 404:
                raise ShopifyAPIError("Shopify returned HTTP 404. Check SHOPIFY_STORE_DOMAIN and "
                                      "SHOPIFY_API_VERSION.")
            if resp.status_code >= 500 and mutation:
                raise ShopifyUnavailableError(
                    f"Shopify returned HTTP {resp.status_code}; the outcome is unknown.")
            if resp.status_code == 429 or resp.status_code >= 500:
                last_problem = f"HTTP {resp.status_code}"
                self._sleep(self._retry_delay(resp, attempt))
                continue
            if resp.status_code != 200:
                raise ShopifyAPIError(f"Shopify returned HTTP {resp.status_code}.")

            try:
                body = resp.json()
            except ValueError:
                raise ShopifyAPIError("Shopify returned a response that was not valid JSON.") from None

            errors = body.get("errors")
            if errors:
                if self._is_throttled(errors):
                    last_problem = "rate limited (THROTTLED)"
                    self._sleep(self._retry_delay(resp, attempt))
                    continue
                raise ShopifyAPIError(self._format_errors(errors))
            return body.get("data") or {}

        raise ShopifyUnavailableError(f"Shopify did not give a usable answer: {last_problem}.")

    @staticmethod
    def _retry_delay(resp: httpx.Response, attempt: int) -> float:
        try:
            return min(float(resp.headers.get("Retry-After", "")), 5.0)
        except ValueError:
            return min(0.5 * (2 ** (attempt - 1)), 5.0)

    @staticmethod
    def _is_throttled(errors) -> bool:
        if not isinstance(errors, list):
            return False
        return any(isinstance(e, dict) and (e.get("extensions") or {}).get("code") == "THROTTLED"
                   for e in errors)

    @staticmethod
    def _format_errors(errors) -> str:
        if isinstance(errors, str):
            return errors[:300]
        msgs = [str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors]
        return ("Shopify GraphQL error: " + "; ".join(msgs))[:500]


# ---- one shared client per process so the 24-hour token is reused ----------
_lock = threading.Lock()
_client: ShopifyClient | None = None
_override: ShopifyClient | None = None


def get_client() -> ShopifyClient:
    global _client
    if _override is not None:
        return _override
    settings = load_settings()
    with _lock:
        if _client is None or _client.settings != settings:
            _client = ShopifyClient(settings)
        return _client


def set_client(client: ShopifyClient | None) -> None:
    """Tests use this to plug in a fake Shopify. Pass None to undo."""
    global _override
    _override = client
