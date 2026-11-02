"""All Shopify-related exceptions. None of them ever contain secrets."""


class ShopifyError(Exception):
    """Base class: anything that stops us from getting a trustworthy answer."""


class ShopifyNotConfiguredError(ShopifyError):
    pass


class ShopifyAuthError(ShopifyError):
    pass


class ShopifyAPIError(ShopifyError):
    pass


class ShopifyUnavailableError(ShopifyError):
    pass


class InventoryLookupError(Exception):
    """The request reached Shopify, but the answer is 'no / ambiguous'."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class OrderExecutionError(Exception):
    """Shopify answered, and said no (validation errors, missing scope...). Nothing was created
    unless `draft_id` says a draft order already exists."""

    def __init__(self, code: str, message: str, draft_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.draft_id = draft_id
