"""agent/content_tools.py — Shopify Content agent tool stubs.

All execution is handled by the guard middleware / gateway; nothing here touches
the Shopify API directly.
"""
from langchain_core.tools import tool


# ── Products ──────────────────────────────────────────────────────────────────

@tool
def list_products(query: str = "", limit: int = 10) -> str:
    """List Shopify products, optionally filtered by a search query. READ-only."""
    raise RuntimeError("executed by middleware")


@tool
def get_product(product_id: str) -> str:
    """Return full details for a single Shopify product by its numeric or GID product ID. READ-only."""
    raise RuntimeError("executed by middleware")


@tool
def create_product(title: str, body_html: str, vendor: str = "",
                   product_type: str = "", tags: str = "",
                   status: str = "draft") -> str:
    """Create a new Shopify product. WRITE — always confirm payload with the user first."""
    raise RuntimeError("write tools execute only inside ToolTruth")


@tool
def update_product(product_id: str, title: str = "", body_html: str = "",
                   vendor: str = "", product_type: str = "",
                   tags: str = "", status: str = "") -> str:
    """Update fields on an existing Shopify product. WRITE — always confirm with the user first."""
    raise RuntimeError("write tools execute only inside ToolTruth")


# ── Pages ─────────────────────────────────────────────────────────────────────

@tool
def list_pages(limit: int = 10) -> str:
    """List Shopify store pages. READ-only."""
    raise RuntimeError("executed by middleware")


@tool
def get_page(page_id: str) -> str:
    """Return the full content of a single Shopify page. READ-only."""
    raise RuntimeError("executed by middleware")


@tool
def create_page(title: str, body_html: str, published: bool = False) -> str:
    """Create a new Shopify page. WRITE — confirm with the user first."""
    raise RuntimeError("write tools execute only inside ToolTruth")


@tool
def update_page(page_id: str, title: str = "", body_html: str = "",
                published: bool | None = None) -> str:
    """Update a Shopify page. WRITE — confirm with the user first."""
    raise RuntimeError("write tools execute only inside ToolTruth")


# ── Blogs & articles ──────────────────────────────────────────────────────────

@tool
def list_blogs(limit: int = 10) -> str:
    """List the blogs in the Shopify store. READ-only."""
    raise RuntimeError("executed by middleware")


@tool
def list_blog_articles(blog_id: str, limit: int = 10) -> str:
    """List articles in a specific Shopify blog. READ-only."""
    raise RuntimeError("executed by middleware")


@tool
def get_blog_article(blog_id: str, article_id: str) -> str:
    """Return full content of a single blog article. READ-only."""
    raise RuntimeError("executed by middleware")


@tool
def create_blog_article(blog_id: str, title: str, body_html: str,
                        author: str = "", tags: str = "",
                        published: bool = False) -> str:
    """Create a blog article. WRITE — confirm with the user first."""
    raise RuntimeError("write tools execute only inside ToolTruth")


@tool
def update_blog_article(blog_id: str, article_id: str,
                        title: str = "", body_html: str = "",
                        author: str = "", tags: str = "",
                        published: bool | None = None) -> str:
    """Update an existing blog article. WRITE — confirm with the user first."""
    raise RuntimeError("write tools execute only inside ToolTruth")


# ── Collections ───────────────────────────────────────────────────────────────

@tool
def list_collections(limit: int = 10) -> str:
    """List custom and smart collections in the Shopify store. READ-only."""
    raise RuntimeError("executed by middleware")


@tool
def get_collection(collection_id: str) -> str:
    """Return details for a single collection. READ-only."""
    raise RuntimeError("executed by middleware")


# ── Metafields ────────────────────────────────────────────────────────────────

@tool
def get_metafields(owner_resource: str, owner_id: str) -> str:
    """List metafields for a Shopify resource (product, page, collection, …). READ-only."""
    raise RuntimeError("executed by middleware")


@tool
def set_metafield(owner_resource: str, owner_id: str,
                  namespace: str, key: str,
                  value: str, value_type: str = "string") -> str:
    """Create or update a metafield. WRITE — confirm with the user first."""
    raise RuntimeError("write tools execute only inside ToolTruth")


# ── Registry ──────────────────────────────────────────────────────────────────

CONTENT_TOOLS = [
    list_products, get_product, create_product, update_product,
    list_pages, get_page, create_page, update_page,
    list_blogs, list_blog_articles, get_blog_article,
    create_blog_article, update_blog_article,
    list_collections, get_collection,
    get_metafields, set_metafield,
]

# Read-only tool names (middleware may execute these without extra confirmation).
CONTENT_READ_TOOLS = {
    "list_products", "get_product",
    "list_pages", "get_page",
    "list_blogs", "list_blog_articles", "get_blog_article",
    "list_collections", "get_collection",
    "get_metafields",
}

# Write tool names (require ToolTruth guard).
CONTENT_WRITE_TOOLS = {
    "create_product", "update_product",
    "create_page", "update_page",
    "create_blog_article", "update_blog_article",
    "set_metafield",
}
