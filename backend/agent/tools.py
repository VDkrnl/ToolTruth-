"""agent/tools.py — the four registered tools. ALL bodies are stubs.

The guard middleware (agent/middleware.py) answers every call by forwarding to
the ToolTruth gateway; nothing in this process can touch a store.
"""
from langchain_core.tools import tool


@tool
def search_products(query: str, max_results: int = 5) -> str:
    """Search the store catalogue. READ-only."""
    raise RuntimeError("executed by middleware")


@tool
def get_product_details(sku: str | None = None, variant_id: str | None = None) -> str:
    """Return price, availability and identifiers for one variant. READ-only."""
    raise RuntimeError("executed by middleware")


@tool
def check_inventory(sku: str, location_id: str | None = None) -> str:
    """Return current available stock with timestamp and source. READ-only."""
    raise RuntimeError("executed by middleware")


@tool
def create_test_order(variant_id: str, sku: str, quantity: int, observation_id: str) -> str:
    """Propose a TEST order. This does NOT place the order; ToolTruth verifies and decides."""
    raise RuntimeError("write tools execute only inside ToolTruth")


ALL_TOOLS = [search_products, get_product_details, check_inventory, create_test_order]
