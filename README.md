# ToolTruth — Typed Consistency Verification Gateway

ToolTruth is a deterministic verification layer between AI agents and external tools. It checks typed state, freshness, contradictions and domain invariants before an agent action is allowed to proceed.

This repository contains both:

1. the **team/project website**, and
2. the **actual ToolTruth research prototype** used by the website to demonstrate verification.

## Current implementation

### Controlled domains

- **E-commerce inventory** — inventory, reservation/sale state and stock/price rules.
- **Software issue / deployment** — issue/deployment state, staging-before-production and issue invariants.
- **Travel booking** — seat/booking state, hold expiry and booking constraints.

All domains are simulators. They do not perform real purchases, production deployments or travel bookings.

### Tool gateway

`POST /gateway/call` is the main boundary for agent tool calls.

The gateway:

1. validates the request structure
2. calls the controlled simulator
3. extracts structured claims deterministically
4. checks freshness and contradictions
5. checks domain invariants
6. records the event
7. stores evidence nodes
8. returns an allow/block decision with reasons

### Evidence

`GET /gateway/evidence/{entity_id}` exposes the provenance trail for claims associated with an entity.

The **Evidence Explorer** page provides a browser-based demonstration of this flow.

### Benchmarks

The repository contains **75 benchmark tasks**:

- 25 e-commerce
- 25 DevOps
- 25 travel

The Benchmark Lab supports:

- `tooltruth`
- `agent_alone`
- `prompt_reflection`
- `schema_only`

It reports task success, precision, recall, F1, false-block rate, unsafe actions prevented and latency.

### SDK

A reusable Python SDK is included under `sdk/`.

## Technology stack

- Frontend: HTML, CSS, vanilla JavaScript
- Backend: FastAPI + SQLAlchemy
- Local database: SQLite
- Production database: PostgreSQL supported
- Local storage: `backend/uploads/`
- Production storage: AWS S3 supported
- Authentication: JWT + bcrypt
- Verification: deterministic Python rules; no external LLM API key required
- Production target: EC2 + Nginx + Certbot + DuckDNS + GitHub Actions

## Fastest Windows local setup

From the project root:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create `backend/.env` from `backend/.env.example` and use the local values documented in **SETUP.md**.

Then:

```powershell
python seed_admin.py
uvicorn main:app --reload --port 8000
```

Open a second terminal:

```powershell
cd frontend
py -m http.server 5500
```

Open:

`http://localhost:5500`

For the complete copy-paste setup and Windows troubleshooting, read **SETUP.md**.

## API quick reference

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | health check |
| `POST /auth/login` | admin login |
| `POST /uploads` | upload deliverables |
| `POST /publish` | publish a version |
| `GET /versions` | list versions |
| `POST /gateway/call` | verify a tool call |
| `GET /gateway/events` | protected event log |
| `GET /gateway/evidence/{entity_id}` | evidence graph |
| `POST /benchmark/run` | protected benchmark run |
| `GET /benchmark/results` | benchmark results endpoint |

Interactive API docs:

`http://127.0.0.1:8000/docs`

## Project website pages

- Home
- Planning presentation
- Archive
- Admin login/dashboard
- Evidence Explorer
- Benchmark Lab

## Team

The current configuration contains the four project team members and their roles in:

`frontend/js/config.js`

## Local storage

Local development does **not** require AWS.

When `S3_BUCKET` is empty or `LOCAL_STORAGE=true`, uploaded files are saved under:

`backend/uploads/`

and are served through the local `/files/serve/{key}` endpoint.

For production, configure S3 and use private bucket access/presigned URLs.

## Verification

Run:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest tests -v --tb=short
```

The current automated suite covers domain behavior, consistency checks and gateway behavior.

## Production deployment

Production deployment is intentionally separate from local setup.

Target architecture:

```text
GitHub Pages
     │
     ▼
Static ToolTruth website
     │ HTTPS
     ▼
DuckDNS hostname
     │
     ▼
Nginx + Certbot
     │
     ▼
FastAPI on EC2
     ├── PostgreSQL
     └── AWS S3
```

See **DEPLOY.md** for deployment planning and **SETUP.md** for local development.

## Security notes

- Never commit `backend/.env`.
- Replace the development JWT secret before production.
- Replace the default admin password before production.
- Keep the S3 bucket private.
- Prefer an EC2 IAM role over long-lived AWS access keys.
- Restrict CORS to the production frontend domain.

## Scope boundary

ToolTruth is a research/engineering prototype. Its three benchmark domains are controlled simulators and intentionally avoid real external side effects.


## Prototype Lab

The implementation includes two new public frontend pages:

- `/prototype/` — deterministic domain state-machine viewer, fault injector, simulation runner, decision certificates, and five-way comparison metrics.
- `/milestone/` — seven-phase roadmap and interactive Frappe Gantt schedule anchored to 2026-08-10.

Prototype API endpoints:

- `GET /prototype/state-machine/{domain}`
- `POST /prototype/simulate`
- `POST /prototype/certificate`
- `GET /prototype/comparison-metrics?domain={domain}`

The protected `/benchmark/run` endpoint remains admin-only. The prototype uses its own public simulation route and isolates benchmark metric generation from the live prototype evidence database.

Decision semantics are deterministic: hard domain/workflow/evidence failures block; stale evidence or user-constraint failures request more evidence; only a fully passing check set allows the action. The claim extractor cannot override the verifier decision.
