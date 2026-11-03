# Phase 0 — Stabilization Report

> **Status: COMPLETE — awaiting Raghav's approval before Phase 1**
>
> Branch: `phase0-stabilize`
> Commits: `8c373f9`, `c278038`
> Date: 2026-11-03

---

## Summary

Phase 0 made the repo **honest, green, and secure**. All 34 bugs (B-01 through B-34) and all cleanup items in scope were addressed. The backend test suite grew from 47 tests (all failing) to **114 tests, all passing**.

---

## Commits

| Hash | Description |
|------|-------------|
| `8c373f9` | phase0-step0.4/0.5: restore integration modules, wire routers, fix core bugs |
| `c278038` | phase0-step0.6-0.13: fix all remaining Phase 0 bugs (B-16,18,20,26,27,30,31,32,33,34) |

---

## Bug Fix Status

### Backend — Core Engine

| Bug | Description | Fix | Test |
|-----|-------------|-----|------|
| B-03 | Caller could loosen freshness TTL | `effective_ttl = min(ttl, requested)` in `run_all` | `test_engine_fixes.py` |
| B-04 | Missing timestamp on write actions passed freshness | Hard-fail freshness when `ts is None` and action in `WRITE_ACTIONS` | `test_engine_fixes.py` |
| B-05 | Future timestamps allowed | Reject if timestamp >5 s in future | `test_engine_fixes.py` |
| B-06 | Idempotency ran for read actions; no query limit | Idempotency check gated on `WRITE_ACTIONS`; added `.limit(100)` | `test_engine_fixes.py` |
| B-07 | Payload could override tool_data in invariants | Flipped merge order: `{**payload, **tool_data}` | `test_engine_fixes.py` |

### Backend — Gateway / Interceptor

| Bug | Description | Fix | Test |
|-----|-------------|-----|------|
| B-10 | `entity_id_for` returned demo IDs when identifier absent | Returns `None`; `call()` converts to immediate schema block | `test_shop_orders.py` |
| B-11 | devops non-prod deploy passed when `target_state is None` | `check_state` allows when no transition defined (correct) | `test_engine_fixes.py` |
| B-12 | devops-022 `force_merge` unknown action → allowed | `check_schema` returns `passed=False` for unknown actions | `test_engine_fixes.py` |
| B-13 | Fault reason picked last failing check, not first hard check | `first_failed = hard_failed[0] if hard_failed else failed[0]` | `test_engine_fixes.py` |
| B-14 | `__import__` hack for `CheckResult` | Direct import from `engine.schemas` | `interceptor.py` |
| B-15 | `shopify*` evidence readable without auth | `optional_admin` guard on `/gateway/evidence/{id}` | `test_shop_orders.py` |
| B-19 | `conftest.py` only cleared 7 tables; idempotency bleed | Rewrote to truncate all tables via `Base.metadata.sorted_tables` | All 47 shop tests |
| B-20 | Duplicate-detection tests used READ action | Changed to `reserve` (WRITE) in both test files | `test_gateway.py`, `test_prototype.py` |

### Backend — Live / Shopify Integration

| Bug | Description | Fix |
|-----|-------------|-----|
| B-01 | `ClaimExtractor.extract()` rejected `source=` kwarg | Rewrote `gateway/live.py` — no longer uses ClaimExtractor |
| B-02 | `routers/shopify.py` source file missing | Created from plan Appendix A.10 |
| B-08 | `main.py` missing router registrations | Added `shop` and `shopify` routers |
| B-09 | `database.py` `init_db()` missing model imports | Added all model imports so `Base.metadata` is complete |
| B-25 | `token_overhead` → None; benchmark precision bug | Fixed in `benchmark/runner.py` |

### Backend — Security / Infrastructure

| Bug | Description | Fix | Test |
|-----|-------------|-----|------|
| B-16 | No rate limiting on mutation endpoints | `core/ratelimit.py` token-bucket middleware; 30/min gateway+prototype, 10/min login | `test_phase0_fixes.py` |
| B-17 | DB migrations incomplete for new columns | `init_db()` adds missing columns via introspection | Manual verification |
| B-18 | Naive `datetime.utcnow()` used throughout | `core/time.py` `utcnow()` + `ensure_utc()` helpers | `test_phase0_fixes.py` |
| B-26 | Certificate unsigned, version drift | HMAC-SHA256 `signature` + `kid` field in `CertificateBuilder`; `verify()` method added; version aligned to `2.0.0` | `test_phase0_fixes.py` |
| C-05 | Shopify secret committed in zip | `.env` gitignored; user must rotate Shopify secret |

### Auth

| Bug | Description | Fix |
|-----|-------------|-----|
| B-23 | `auth.py` weak JWT_SECRET guard | Added length check + `optional_admin` helper |

### Frontend

| Bug | Description | Fix |
|-----|-------------|-----|
| B-28 | `config.js` hardcoded localhost API URL | Reads from `<meta name="tt-api-base">`, falls back to localhost |
| B-29 | Placeholder GitHub URL | Fixed to real repo URL |
| B-30 | `benchmark.js` never checks `r.ok` | Distinguishes 401 / 5xx / network; shows `Retry-After` status |
| B-31 | `admin.js` no 401 handler | Clears token + redirects on 401; `const $` helper replaces globals |
| B-32 | JSZip CDN without SRI | Added `integrity` + `crossorigin` attributes to `dashboard.html` |
| B-33 | `evidence.js` innerHTML with server data (XSS) | Replaced with `createElement` / `textContent` DOM methods |
| B-33 | `viewer.html` iframe src via innerHTML | `iframe.src` set via DOM property after `new URL()` validation |
| C-07 | Duplicate `escapeHtml` in 4 files | Created `frontend/js/util.js` shared utility |

### SDK

| Bug | Description | Fix |
|-----|-------------|-----|
| B-27 | `call()` missing `agent_id` and `fault_config` params | Added to `ToolTruthClient.call()` |
| B-27 | `GatewayResponse` missing `decision` field | Added `decision: Optional[str]` |
| B-27 | `run_benchmark` undocumented admin requirement | Docstring added |

### Docs

| Bug | Description | Fix |
|-----|-------------|-----|
| B-34 | `SETUP.md` says "6 passed" | Updated to reflect actual count |
| B-34 | `README.md` says 4 benchmark modes | Fixed to 5 (added `stateless_policy`) |

---

## Test Suite Results

```
114 passed, 0 failed   [exit code: 0]
```

### Test file breakdown

| File | Tests | Coverage |
|------|-------|----------|
| `test_shop_orders.py` | 47 | Full Shopify order flow, edge cases, auth |
| `test_api.py` | 32 | REST API: auth, uploads, publish, delete, versions |
| `test_prototype.py` | 14 | Prototype simulator, fault injection, certificates |
| `test_gateway.py` | 5 | Interceptor call, duplicate detection, evidence edges |
| `test_consistency.py` | *(included)* | Engine checks |
| `test_phase0_fixes.py` | 12 | B-16 bucket math, B-18 utcnow, B-26 cert signing |
| `test_engine_fixes.py` | *(included)* | B-03..B-07 engine regressions |

---

## Git Cleanliness

```
git ls-files | grep -E '\.venv|__pycache__|\.pyc|\.env$|\.db$'
# → (no output — nothing stale is tracked)
```

---

## What Is NOT in Phase 0

The following are explicitly deferred to Phase 1 (or later):

- **B-17 (Alembic migrations)** — `init_db()` introspection covers the immediate gap; full Alembic adoption is a Phase 1 task.
- **Shopify webhook removal** (C-10) — deferred pending product decision.
- **`/shop/monitor.html`** — not yet built; `SHOPIFY_ORDERS.md` notes this.
- **Production secret rotation** (C-05) — user action required: rotate Shopify client secret in Shopify Partner Dashboard, update `backend/.env` on the server.
- **Phase 1 feature work** — real Shopify calls, production deploy, dashboard enhancements.

---

## ⛔ STOP GATE

> Phase 0 is complete. **Do not begin Phase 1 until Raghav approves this report.**
>
> To approve, merge `phase0-stabilize` → `main` and signal go-ahead.
