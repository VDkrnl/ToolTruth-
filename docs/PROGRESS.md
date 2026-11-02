# Phase 0 Progress Tracker

Branch: `phase0-stabilize`

## OrderService public methods (from `gateway/order_flow.py`)

| Method | Purpose |
|---|---|
| `place_order(req: dict) -> dict` | Entry point — schema check, idempotency replay, then verify + execute |
| `get_result(run_id: str) -> dict \| None` | Look up a stored attempt by run_id |
| `_check_schema(req)` | Validates cart, customer, idempotency_key, max_age_seconds |
| `_request_hash(cart, customer, req)` | SHA-256 of canonical cart+email for idempotency comparison |
| `_replay(existing, digest, req, cart, customer)` | Handle a repeated idempotency key |
| `_verify_and_execute(attempt, req, schema, cart, customer, replayed)` | Full pipeline under `_ORDER_LOCK` |
| `_check_snapshot_age(observed_at, max_age)` | Freshness of the customer's price/stock snapshot |
| `_check_line(line, found, fetched_at, observed_at)` | Per-SKU checks: product_active, location_resolved, sufficient_inventory, source_consistency, freshness |
| `_execute(attempt, lines, email, resume)` | Draft order → complete → read-back proof; never blind-retries a mutation |
| `_reconcile(attempt, req, cart, customer)` | Re-run after uncertain outcome: tag lookup → resume |
| `_finish(attempt, checks, lines, evidence, execution, replayed)` | Commit decision, status, EventLog |
| `_present(attempt, replayed)` | Build the response dict from a stored attempt |

## OrderAttempt columns (from `gateway/models.py`)

| Column | Type | Notes |
|---|---|---|
| `run_id` | String(64) UNIQUE | UUID hex |
| `idempotency_key` | String(80) UNIQUE | Caller-supplied key |
| `request_hash` | String(64) | SHA-256 of canonical cart+email |
| `status` | String(30) | verifying / executing / rejected / needs_evidence / verified_not_executed / executed_verified / executed_unverified / execution_failed / uncertain |
| `decision` | String(30) | allow / block / request_more_evidence |
| `reason` | Text | Human-readable explanation |
| `shopify_tag` | String(60) | `tt-<sha256(key)[:32]>` used to look up drafts |
| `order_mode` | String(20) | complete / draft |
| `cart_json` | Text | JSON list of `{sku, quantity, observed_available}` |
| `customer_json` | Text | Masked `{name, email_masked}` |
| `checks_json` | Text | Serialised CheckResult list |
| `lines_json` | Text | Per-SKU verification details |
| `evidence_json` | Text | Evidence node dicts |
| `execution_json` | Text | Draft/order ids, outcome, verification |
| `shopify_order_id` | String(120) nullable | GID of completed order |
| `shopify_order_name` | String(60) nullable | e.g. `#1001` |
| `created_at` | DateTime | Naive UTC |
| `updated_at` | DateTime | Naive UTC |

## Confirmed missing files (B-01)
- `routers/shopify.py` — **restored** ✅
- `gateway/live.py` — **rewritten** ✅ (was referencing stale `ClaimExtractor.extract(source=…)` API)
- `integrations/shopify/webhooks.py` — intentionally excluded (C-10: out of scope)

## Phase 0 Steps

| Step | Status | Notes |
|---|---|---|
| 0.1 Read-only audit | ✅ | This file |
| 0.2 Secrets / .gitignore | ✅ | .gitignore updated; .env excluded |
| 0.3 Hygiene | ✅ | .gitignore covers venv/pyc/db/.pytest_cache |
| 0.4 Restore Shopify modules | ✅ | live.py rewritten; routers/shopify.py created |
| 0.5 Commit untracked Shopify work | ✅ | Committed on phase0-stabilize |
| 0.6 Engine fixes B-03,04,05,06,07 | ⬜ | Pending |
| 0.7 Gateway fixes B-10,11,13,14 | ⬜ | Pending |
| 0.8 Benchmark honesty B-12,25 | ⬜ | Pending |
| 0.9 Security B-15,16,21 | ✅ | B-15 evidence endpoint gated; B-21 auth.py hardened |
| 0.10 DB B-17,18,19,20 | ✅ | B-19 conftest truncates all tables; B-09 routers registered |
| 0.11 Dead code & cleanup B-08,C-07..C-16 | ⬜ | Pending |
| 0.12 Deps/CI/deploy B-22,23,24 | ✅ | workers=1; CI fixed; requirements split |
| 0.13 Frontend B-28..33 | ⬜ | Pending |
| 0.14 SDK & docs B-27,34 | ⬜ | Pending |
| 0.15 Phase 0 report | ⬜ | Pending |

## Test Results After Fixes
- `test_shop_orders.py` → **47 passed** ✅
- Full suite → **93 passed** ✅
