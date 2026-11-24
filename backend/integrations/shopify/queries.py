"""All GraphQL text lives here so it is easy to review and update."""

QUANTITY_NAMES = ["available", "on_hand", "committed", "reserved",
                  "damaged", "safety_stock", "quality_control", "incoming"]

# Needs scopes: read_inventory, read_products (variant), read_locations (location).
INVENTORY_BY_SKU = """
query InventoryBySku($query: String!) {
  inventoryItems(first: 5, query: $query) {
    edges {
      node {
        id
        sku
        tracked
        variant { id title price product { id title } }
        inventoryLevels(first: 50) {
          edges {
            node {
              id
              updatedAt
              location { id name }
              quantities(names: ["available","on_hand","committed","reserved","damaged","safety_stock","quality_control","incoming"]) {
                name
                quantity
                updatedAt
              }
            }
          }
        }
      }
    }
  }
}
"""

SHOP_INFO = "query { shop { name myshopifyDomain } }"

REGISTER_WEBHOOK = """
mutation RegisterWebhook($topic: WebhookSubscriptionTopic!, $sub: WebhookSubscriptionInput!) {
  webhookSubscriptionCreate(topic: $topic, webhookSubscription: $sub) {
    webhookSubscription { id topic uri }
    userErrors { field message }
  }
}
"""

# ---------------------------------------------------------------- catalog / variants
# Needs scopes: read_products, read_inventory, read_locations.
VARIANT_FIELDS = """
      id
      sku
      title
      price
      image { url }
      product { id title status featuredImage { url } }
      inventoryItem {
        id
        tracked
        inventoryLevels(first: 20) {
          edges {
            node {
              updatedAt
              location { id name }
              quantities(names: ["available","on_hand","committed","reserved","damaged","safety_stock","quality_control","incoming"]) {
                name
                quantity
                updatedAt
              }
            }
          }
        }
      }
"""

CATALOG_PAGE = """
query CatalogPage($first: Int!, $after: String, $query: String) {
  shop { currencyCode }
  productVariants(first: $first, after: $after, query: $query) {
    pageInfo { hasNextPage endCursor }
    edges { node {""" + VARIANT_FIELDS + """} }
  }
}
"""

# ---------------------------------------------------------------- orders (need write_draft_orders)
DRAFT_ORDER_CREATE = """
mutation DraftOrderCreate($input: DraftOrderInput!) {
  draftOrderCreate(input: $input) {
    draftOrder { id name status tags }
    userErrors { field message }
  }
}
"""

DRAFT_ORDER_COMPLETE = """
mutation DraftOrderComplete($id: ID!, $paymentPending: Boolean) {
  draftOrderComplete(id: $id, paymentPending: $paymentPending) {
    draftOrder { id name status order { id name } }
    userErrors { field message }
  }
}
"""

# Needs read_draft_orders.
DRAFT_ORDERS_BY_TAG = """
query DraftOrdersByTag($query: String!) {
  draftOrders(first: 5, query: $query) {
    edges { node { id name status tags order { id name } } }
  }
}
"""

DRAFT_ORDER_BY_ID = """
query DraftOrderById($id: ID!) {
  draftOrder(id: $id) {
    id name status tags
    order { id name }
    lineItems(first: 50) { edges { node { sku quantity variant { id } } } }
  }
}
"""

# Needs read_orders.
ORDER_BY_ID = """
query OrderById($id: ID!) {
  order(id: $id) {
    id name createdAt tags displayFinancialStatus
    lineItems(first: 50) { edges { node { sku quantity variant { id } } } }
  }
}
"""
