"""services/agent_shopify_content.py — Shopify Content provider for the content agent.

Implements read and write handlers for the Shopify Content agent tools.
All Shopify API calls go through the integrations.shopify client; the agent
process never receives Shopify credentials.
"""
import uuid

from integrations.shopify import get_client
from integrations.shopify.config import load_settings
from integrations.shopify.errors import ShopifyError


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _env(tool: str, session_id: str, result, errors=None):
    """Build a standard content-agent envelope (no order/decision fields)."""
    oid = None
    if result is not None:
        oid = "cobs_" + uuid.uuid4().hex[:12]
    return {
        "tool": tool,
        "access": "READ" if _is_read(tool) else "WRITE",
        "provider": "shopify_content",
        "live": True,
        "observation_id": oid,
        "result": result,
        "errors": errors or [],
    }


_READ_TOOLS = {
    "list_products", "get_product",
    "list_pages", "get_page",
    "list_blogs", "list_blog_articles", "get_blog_article",
    "list_collections", "get_collection",
    "get_metafields",
}


def _is_read(tool: str) -> bool:
    return tool in _READ_TOOLS


def _not_configured():
    return {"errors": ["shopify_not_configured"]}


# ---------------------------------------------------------------------------
# Public read handler
# ---------------------------------------------------------------------------

def read(tool: str, session_id: str, args: dict, db) -> dict:  # noqa: ARG001
    """Handle read-only content tools."""
    settings = load_settings()
    if not settings.configured:
        return _env(tool, session_id, None, ["shopify_not_configured"])
    client = get_client()
    try:
        # ── Products ──────────────────────────────────────────────────────
        if tool == "list_products":
            query = args.get("query", "")
            limit = int(args.get("limit", 10))
            endpoint = f"/admin/api/2024-01/products.json?limit={limit}"
            if query:
                endpoint += f"&title={query}"
            data = client.get(endpoint)
            items = [
                {
                    "id": p["id"],
                    "title": p["title"],
                    "vendor": p.get("vendor", ""),
                    "product_type": p.get("product_type", ""),
                    "status": p.get("status", ""),
                    "tags": p.get("tags", ""),
                    "variants_count": len(p.get("variants", [])),
                }
                for p in data.get("products", [])
            ]
            return _env(tool, session_id, {"items": items})

        if tool == "get_product":
            pid = args.get("product_id", "")
            if not pid:
                return _env(tool, session_id, None, ["product_id required"])
            data = client.get(f"/admin/api/2024-01/products/{pid}.json")
            return _env(tool, session_id, data.get("product"))

        # ── Pages ─────────────────────────────────────────────────────────
        if tool == "list_pages":
            limit = int(args.get("limit", 10))
            data = client.get(f"/admin/api/2024-01/pages.json?limit={limit}")
            items = [
                {"id": p["id"], "title": p["title"],
                 "published": bool(p.get("published_at")),
                 "updated_at": p.get("updated_at", "")}
                for p in data.get("pages", [])
            ]
            return _env(tool, session_id, {"items": items})

        if tool == "get_page":
            pid = args.get("page_id", "")
            if not pid:
                return _env(tool, session_id, None, ["page_id required"])
            data = client.get(f"/admin/api/2024-01/pages/{pid}.json")
            return _env(tool, session_id, data.get("page"))

        # ── Blogs ─────────────────────────────────────────────────────────
        if tool == "list_blogs":
            limit = int(args.get("limit", 10))
            data = client.get(f"/admin/api/2024-01/blogs.json?limit={limit}")
            items = [{"id": b["id"], "title": b["title"]} for b in data.get("blogs", [])]
            return _env(tool, session_id, {"items": items})

        if tool == "list_blog_articles":
            blog_id = args.get("blog_id", "")
            limit = int(args.get("limit", 10))
            if not blog_id:
                return _env(tool, session_id, None, ["blog_id required"])
            data = client.get(f"/admin/api/2024-01/blogs/{blog_id}/articles.json?limit={limit}")
            items = [
                {"id": a["id"], "title": a["title"],
                 "author": a.get("author", ""),
                 "published": bool(a.get("published_at"))}
                for a in data.get("articles", [])
            ]
            return _env(tool, session_id, {"items": items})

        if tool == "get_blog_article":
            blog_id = args.get("blog_id", "")
            article_id = args.get("article_id", "")
            if not blog_id or not article_id:
                return _env(tool, session_id, None, ["blog_id and article_id required"])
            data = client.get(
                f"/admin/api/2024-01/blogs/{blog_id}/articles/{article_id}.json"
            )
            return _env(tool, session_id, data.get("article"))

        # ── Collections ───────────────────────────────────────────────────
        if tool == "list_collections":
            limit = int(args.get("limit", 10))
            custom = client.get(
                f"/admin/api/2024-01/custom_collections.json?limit={limit}"
            ).get("custom_collections", [])
            smart = client.get(
                f"/admin/api/2024-01/smart_collections.json?limit={limit}"
            ).get("smart_collections", [])
            items = [
                {"id": c["id"], "title": c["title"], "type": "custom"} for c in custom
            ] + [
                {"id": c["id"], "title": c["title"], "type": "smart"} for c in smart
            ]
            return _env(tool, session_id, {"items": items})

        if tool == "get_collection":
            cid = args.get("collection_id", "")
            if not cid:
                return _env(tool, session_id, None, ["collection_id required"])
            # Try custom first, fall back to smart.
            try:
                data = client.get(f"/admin/api/2024-01/custom_collections/{cid}.json")
                return _env(tool, session_id, data.get("custom_collection"))
            except ShopifyError:
                data = client.get(f"/admin/api/2024-01/smart_collections/{cid}.json")
                return _env(tool, session_id, data.get("smart_collection"))

        # ── Metafields ────────────────────────────────────────────────────
        if tool == "get_metafields":
            resource = args.get("owner_resource", "")
            owner_id = args.get("owner_id", "")
            if not resource or not owner_id:
                return _env(tool, session_id, None, ["owner_resource and owner_id required"])
            data = client.get(
                f"/admin/api/2024-01/metafields.json"
                f"?metafield[owner_resource]={resource}&metafield[owner_id]={owner_id}"
            )
            return _env(tool, session_id, {"metafields": data.get("metafields", [])})

        return _env(tool, session_id, None, [f"unknown_tool: {tool}"])

    except ShopifyError as exc:
        return _env(tool, session_id, None, [f"shopify_unavailable: {exc}"[:200]])


# ---------------------------------------------------------------------------
# Public write handler
# ---------------------------------------------------------------------------

def write(tool: str, session_id: str, args: dict, db) -> dict:  # noqa: ARG001
    """Handle write content tools."""
    settings = load_settings()
    if not settings.configured:
        return _env(tool, session_id, None, ["shopify_not_configured"])
    client = get_client()
    try:
        # ── Products ──────────────────────────────────────────────────────
        if tool == "create_product":
            payload = {
                "product": {
                    "title": args.get("title", ""),
                    "body_html": args.get("body_html", ""),
                    "vendor": args.get("vendor", ""),
                    "product_type": args.get("product_type", ""),
                    "tags": args.get("tags", ""),
                    "status": args.get("status", "draft"),
                }
            }
            data = client.post("/admin/api/2024-01/products.json", payload)
            return _env(tool, session_id, data.get("product"))

        if tool == "update_product":
            pid = args.get("product_id", "")
            if not pid:
                return _env(tool, session_id, None, ["product_id required"])
            fields = {k: v for k, v in {
                "title": args.get("title"),
                "body_html": args.get("body_html"),
                "vendor": args.get("vendor"),
                "product_type": args.get("product_type"),
                "tags": args.get("tags"),
                "status": args.get("status"),
            }.items() if v}
            data = client.put(f"/admin/api/2024-01/products/{pid}.json", {"product": fields})
            return _env(tool, session_id, data.get("product"))

        # ── Pages ─────────────────────────────────────────────────────────
        if tool == "create_page":
            payload = {
                "page": {
                    "title": args.get("title", ""),
                    "body_html": args.get("body_html", ""),
                    "published": bool(args.get("published", False)),
                }
            }
            data = client.post("/admin/api/2024-01/pages.json", payload)
            return _env(tool, session_id, data.get("page"))

        if tool == "update_page":
            pid = args.get("page_id", "")
            if not pid:
                return _env(tool, session_id, None, ["page_id required"])
            fields: dict = {}
            if args.get("title"):
                fields["title"] = args["title"]
            if args.get("body_html"):
                fields["body_html"] = args["body_html"]
            if args.get("published") is not None:
                fields["published"] = bool(args["published"])
            data = client.put(f"/admin/api/2024-01/pages/{pid}.json", {"page": fields})
            return _env(tool, session_id, data.get("page"))

        # ── Blog articles ─────────────────────────────────────────────────
        if tool == "create_blog_article":
            blog_id = args.get("blog_id", "")
            if not blog_id:
                return _env(tool, session_id, None, ["blog_id required"])
            payload = {
                "article": {
                    "title": args.get("title", ""),
                    "body_html": args.get("body_html", ""),
                    "author": args.get("author", ""),
                    "tags": args.get("tags", ""),
                    "published": bool(args.get("published", False)),
                }
            }
            data = client.post(
                f"/admin/api/2024-01/blogs/{blog_id}/articles.json", payload
            )
            return _env(tool, session_id, data.get("article"))

        if tool == "update_blog_article":
            blog_id = args.get("blog_id", "")
            article_id = args.get("article_id", "")
            if not blog_id or not article_id:
                return _env(tool, session_id, None, ["blog_id and article_id required"])
            fields = {k: v for k, v in {
                "title": args.get("title"),
                "body_html": args.get("body_html"),
                "author": args.get("author"),
                "tags": args.get("tags"),
                "published": args.get("published"),
            }.items() if v is not None and v != ""}
            data = client.put(
                f"/admin/api/2024-01/blogs/{blog_id}/articles/{article_id}.json",
                {"article": fields},
            )
            return _env(tool, session_id, data.get("article"))

        # ── Metafields ────────────────────────────────────────────────────
        if tool == "set_metafield":
            payload = {
                "metafield": {
                    "owner_resource": args.get("owner_resource", ""),
                    "owner_id": args.get("owner_id", ""),
                    "namespace": args.get("namespace", ""),
                    "key": args.get("key", ""),
                    "value": args.get("value", ""),
                    "type": args.get("value_type", "string"),
                }
            }
            data = client.post("/admin/api/2024-01/metafields.json", payload)
            return _env(tool, session_id, data.get("metafield"))

        return _env(tool, session_id, None, [f"unknown_write_tool: {tool}"])

    except ShopifyError as exc:
        return _env(tool, session_id, None, [f"shopify_unavailable: {exc}"[:200]])
