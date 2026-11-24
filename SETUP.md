# ToolTruth — Complete Local Setup (Windows / PowerShell)

This guide is for the ToolTruth ZIP. It runs the complete current project locally with **zero cloud services**. SQLite is used for the database and local disk is used for file uploads. AWS S3, PostgreSQL and EC2 are not required for local development.

The current ZIP also contains the ToolTruth simulator, gateway, consistency engine, evidence explorer, benchmark lab and SDK. The local setup below gets all of those components running.

## 1. Requirements

Install:
- Python 3.10+ (Python 3.13 recommended)
- VS Code (recommended)
- Chrome or Edge
- Git (optional for later deployment)

Check Python:

```powershell
py --version
```

## 2. Extract the ZIP

Extract the ZIP to a simple path, for example:

`C:\ToolTruth`

Open the extracted **ToolTruth** folder in VS Code.

Your structure should look like:

```text
ToolTruth/
├── backend/
├── frontend/
├── sdk/
├── README.md
└── SETUP.md
```

## 3. Create the backend virtual environment

Open a PowerShell terminal in VS Code and run:

```powershell
cd backend
py -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then activate again.

> **Important:** Do not copy a `.venv` folder from another computer. If you already have a broken `.venv`, delete it and recreate it with the commands above.

## 4. Install dependencies

With `(.venv)` visible in the terminal:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 5. Configure the local environment

Inside `backend`, create a new file named exactly:

`.env`

> **Frontend API note:** the deployment-ready `frontend/js/config.js` points to `https://api.tooltruth.duckdns.org`. For a local-only demo, temporarily change `API_BASE_URL` there to `http://127.0.0.1:8000`.

Do not rename `.env.example`; copy its contents into `.env`.

Use:

```env
# Database — SQLite (local file, no PostgreSQL needed)
DATABASE_URL=sqlite:///./tooltruth.db

# Auth
JWT_SECRET=local-dev-secret-tooltruth-2026-change-before-production
JWT_EXPIRE_MINUTES=60
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123

# AWS S3 — leave empty to use local disk instead
S3_BUCKET=
AWS_REGION=ap-south-1

# API
CORS_ORIGINS=http://localhost:5500,http://127.0.0.1:5500
MAX_FILE_SIZE_MB=25

# Storage mode — true uses backend/uploads instead of S3
LOCAL_STORAGE=true
```

### What this means

- `DATABASE_URL` → creates a local `backend/tooltruth.db` SQLite database.
- `JWT_SECRET` → signs admin login tokens. Replace it before production.
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` → local admin credentials.
- `S3_BUCKET=` → intentionally empty, so uploads use local disk.
- `CORS_ORIGINS` → allows the frontend on port 5500 to call the backend on port 8000.
- `LOCAL_STORAGE=true` → explicitly enables local file storage.

You do **not** need AWS credentials for this local setup.

## 6. Create the admin account

From `backend`:

```powershell
python seed_admin.py
```

Expected first-time output:

```text
Created admin: admin
```

Local login:

```text
Username: admin
Password: admin123
```

If it says `Admin already exists`, that is fine. To reset the local database completely, stop the backend and remove `backend/tooltruth.db`, then run `python seed_admin.py` again.

## 7. Run the backend

Keep the first terminal open:

```powershell
python seed_admin.py
```

Expected:

```text
Uvicorn running on http://127.0.0.1:8000
```

Open:

`http://127.0.0.1:8000/healthz`

Expected JSON:

```json
{"status":"ok","service":"tooltruth-api","version":"2.0.0"}
```

API documentation:

`http://127.0.0.1:8000/docs`

## 8. Run the frontend

Open a **second PowerShell terminal**. Keep the backend terminal running.

From the project root:

```powershell
cd frontend
py -m http.server 5500
```

Open:

`http://localhost:5500`

Do not double-click the HTML files. Use the HTTP server.

## 9. Test the website

### Public pages

- Home: `http://localhost:5500/`
- Evidence Explorer: `http://localhost:5500/evidence/`
- Benchmark Lab: `http://localhost:5500/benchmark/`
- Planning: `http://localhost:5500/presentations/v1.html`
- Archive: `http://localhost:5500/presentations/archive.html`
- Admin login: `http://localhost:5500/admin/login.html`

### Admin test

1. Open Admin Login.
2. Enter `admin` / `admin123`.
3. You should reach the dashboard.
4. Select a PDF, PPTX, DOCX, ZIP or supported image.
5. Upload it.
6. The file is stored under `backend/uploads/`.
7. Publish the uploaded file.
8. Open Archive and verify the published version appears.

## 10. Test ToolTruth itself

Open Evidence Explorer.

Choose a domain and action, then click **Run through gateway**.

The request goes to:

`POST /gateway/call`

The response contains:
- `allowed`
- `reason`
- `fault_type`
- consistency checks
- evidence trail

After the call, load the entity evidence to see the stored claims.

## 11. Run the benchmark

The Benchmark Lab uses the admin token, so log in first.

There are:
- 25 e-commerce tasks
- 25 DevOps tasks
- 25 travel tasks
- 75 total tasks

Select a domain and mode, then click **Run 25 tasks**.

Supported modes:
- `tooltruth`
- `agent_alone`
- `prompt_reflection`
- `schema_only`

## 12. Run automated tests

Open a third PowerShell terminal, or stop the frontend server temporarily, then:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest tests -v --tb=short
```

Expected current result:

```text
6 passed
```

## 13. SDK test

From the project root, while the backend is running:

```powershell
cd sdk
python -m pip install -e .
```

Then:

```powershell
python -c "from tooltruth import ToolTruthClient; print(ToolTruthClient('http://127.0.0.1:8000').call('ecommerce','get_inventory',{'product_id':'SKU-100'}))"
```

## 14. Common Windows problems

### `Fatal error in launcher`

This usually means `.venv` was copied from another computer/path.

Fix:

```powershell
cd backend
deactivate
Remove-Item -Recurse -Force .venv
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### `ModuleNotFoundError`

Make sure `(.venv)` is visible in the terminal, then run:

```powershell
python -m pip install -r requirements.txt
```

### Port 8000 already in use

```powershell
netstat -ano | findstr :8000
```

Or run:

```powershell
uvicorn main:app --reload --port 8001
```

If you change the backend port, update `frontend/js/config.js` too.

### Port 5500 already in use

```powershell
py -m http.server 5501
```

Then add `http://localhost:5501` to `CORS_ORIGINS` in `backend/.env` and update the frontend URL only if needed.

### CORS error

Check:
1. Backend is running.
2. `/healthz` opens successfully.
3. `frontend/js/config.js` uses `http://127.0.0.1:8000`.
4. `backend/.env` contains `http://localhost:5500,http://127.0.0.1:5500`.

### Upload fails

Check that `backend/uploads/` can be created. It is created automatically on the first successful upload.

### Archive is empty

The archive first tries the API. If the API is unavailable, it displays the static Planning v1 entry. Make sure `frontend/js/config.js` has `DEMO_MODE: false` and the backend is running for live versions.

## 15. Local storage behavior

When `S3_BUCKET` is empty or `LOCAL_STORAGE=true`:

```text
backend/uploads/
```

stores uploaded files locally.

The backend serves them through:

`GET /files/serve/{key}`

When S3 is configured later, uploads can switch to S3 and presigned URLs.

## 16. Project structure

```text
ToolTruth/
├── backend/
│   ├── domains/          # controlled e-commerce, DevOps and travel simulators
│   ├── engine/           # deterministic consistency checks
│   ├── gateway/          # event log, evidence graph and interceptor
│   ├── benchmark/        # benchmark runner + 75 tasks
│   ├── routers/          # REST API routes
│   ├── tests/            # automated tests
│   ├── uploads/          # local uploaded files (created at runtime)
│   └── main.py
├── frontend/
│   ├── evidence/         # evidence explorer
│   ├── benchmark/        # benchmark dashboard
│   ├── admin/            # admin login/dashboard
│   └── presentations/    # planning/archive pages
├── sdk/                  # reusable Python client
├── README.md
├── SETUP.md
└── DEPLOY.md
```

## 17. What you should do next

For the local demo, get these working in order:

1. `/healthz`
2. Home page
3. Admin login
4. Upload + publish
5. Archive
6. Evidence Explorer
7. Benchmark Lab
8. `pytest tests -v`
9. SDK test

Only after all of these work should you start the AWS/EC2/DuckDNS deployment.
