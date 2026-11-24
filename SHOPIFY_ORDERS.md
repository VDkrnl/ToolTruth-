# ToolTruth × Shopify: verified customer orders

A customer builds a cart on `/shop`. The **backend** re-reads Shopify, runs the ToolTruth checks, and
only if the decision is **ALLOW** creates the order in Shopify, then reads it back to prove it exists.
The browser never talks to Shopify and cannot skip the checks.

```
/shop (browser) ──▶ POST /shop/orders ──▶ fresh Shopify read ──▶ checks ──▶ decision
                                                                      │
                          BLOCK / REQUEST MORE EVIDENCE ◀─────────────┤  (nothing created)
                                                                      ▼ ALLOW
                       draftOrderCreate ─▶ draftOrderComplete (payment pending) ─▶ read order back
```

## 1. One-time setup (do this before the demo)

1. **Rotate the Shopify client secret.** It was pasted into a chat, so treat it as exposed: Shopify
   Dev Dashboard → your app → Settings → rotate secret → put the new value in `backend/.env`.
   Never commit `backend/.env` (it is already in `.gitignore`).
2. Set a strong `JWT_SECRET` and `ADMIN_PASSWORD` in `backend/.env`, then run `python seed_admin.py`.
3. **Add the order scopes** to the app (create a new app version in the Dev Dashboard): 
   `write_draft_orders`, `read_draft_orders`, `read_orders` (plus the read scopes you already have:
   `read_products`, `read_inventory`, `read_locations`). Release the version and approve the updated
   permissions on the development store. Without them the flow still verifies, and reports
   *"Orders cannot be created: the Shopify app is missing the scope(s) …"*.
4. In `backend/.env` add:
   ```
   SHOPIFY_ORDERS_ENABLED=true
   SHOPIFY_ORDER_MODE=complete
   SHOPIFY_DEFAULT_LOCATION_ID=<your location id>   # needed only if products are stocked at 2+ locations
   ```
5. Restart the backend. Open the admin **Order monitor** (`/shop/monitor.html`): *Connection* should say
   Connected and *Missing order scopes: none*.
6. Use the **development store only**. The flow never collects payment: orders are created with payment pending.

Products must be **Active**, have a **SKU**, and have **Track quantity** on.

## 2. The decision rules

| Decision | When | Result |
|---|---|---|
| **ALLOW** | every check passed | order created, then read back from Shopify |
| **BLOCK** | bad input; unknown or duplicate SKU; product not Active; stock not tracked; not enough stock; same key reused for another cart | nothing created |
| **REQUEST MORE EVIDENCE** | the customer's stock snapshot is older than 5 min; stock changed since the snapshot; Shopify's own numbers disagree; location unclear; Shopify unreachable; server busy | nothing created; the page offers *Refresh stock & review cart* |

If checks of both kinds fail, **BLOCK wins** and its reason is shown first.

Order result states: `executed_verified` (the normal success), `executed_unverified` (order exists but the
read-back could not confirm it: look at it in Shopify Admin), `execution_failed` (Shopify refused),
`uncertain` (Shopify never answered; see below), `verified_not_executed` (ordering switched off).

## 3. Safety design

* **Idempotency.** The page sends a random key per order. The key is unique in the database, so sending
  it again returns the saved result and never creates a second order. The same key with a different cart is a 409 BLOCK.
* **No blind retries.** A timeout or 5xx on a *mutation* is never retried by the client. ToolTruth looks
  for the record in Shopify (the draft order is tagged `tt-<hash of the key>`) before doing anything else. If it
  cannot be found, the attempt is marked `uncertain` and left for a human; sending the same key later checks again.
* **Concurrency.** Verify + execute runs under one lock per server process, so two customers cannot both
  take the last unit. **Run a single uvicorn worker** (no `--workers N`). With several workers
  Shopify still will not over-commit stock and the read-back still proves what happened, but two orders could both pass
  verification at the same moment.
* **Public endpoints are bounded**: request size limit, per-visitor rate limit (`SHOP_RATE_LIMIT_*`),
  max 10 lines / quantity 10 per line, email masked in results. `/shop/admin/*` and Shopify evidence need an admin login.
* Customer details are demo-only; only the email goes to Shopify (the order's contact email).

## 4. Evidence

Each attempt stores: every check, each SKU's observed quantities with timestamps, the decision, and the Shopify
order reference. In the **Evidence Explorer** (admin login): entity `shopify-order:<run_id>` holds the decision
and order claims; entity `shopify:<SKU>:<location>` holds the stock readings that justified it. The result page's
*View evidence* button deep-links to the first.

## 5. API

| Route | Who | Purpose |
|---|---|---|
| `GET /shop/catalog` | public | live products, prices, stock (Active products only) |
| `POST /shop/orders` | public | verify and (if ALLOW) create. Body: `idempotency_key`, `items[{sku,quantity,observed_available?}]`, `customer{name,email}`, `observed_at?` |
| `GET /shop/orders/{run_id}` | public (unguessable id) | saved result |
| `GET /shop/admin/orders`, `GET /shop/admin/monitor` | admin | order list; connection health, scopes, decision counts, items needing attention |

## 6. Tests

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m pytest -q                       # everything
python -m pytest tests/test_shop_orders.py -q
```
`tests/test_shop_orders.py` uses a fake Shopify (no internet) and covers the seven demo cases: valid order,
insufficient stock, unknown SKU, stale snapshot, duplicate request, changed stock, concurrent orders for the last unit;
plus timeouts, missing scope, read-back mismatch, pagination and the HTTP API.

## 7. Demo script (about 3 minutes)

1. `/shop`: products are live from Shopify. Add 2 of a product, **Place order** → **ALLOW**, order `#10xx`, "read back from Shopify: yes". Show it in Shopify Admin → Orders (payment pending).
2. Ask for more than is in stock → **BLOCK**, nothing created.
3. Add to cart, then change that product's stock in Shopify Admin, then Place order → **REQUEST MORE EVIDENCE** ("stock changed from X to Y"). Click *Refresh stock & review cart*, order again → ALLOW.
4. **View evidence** (signed in as admin) and the **Order monitor**.

## 8. Not included yet

Webhook-driven live refresh of the storefront, payments, customer accounts, multi-location allocation, and a
multi-worker-safe lock (a database advisory lock would be the next step).
