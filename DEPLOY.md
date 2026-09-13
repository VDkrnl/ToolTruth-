# ToolTruth deployment guide

## 1. Repository

Push this project to GitHub. Enable GitHub Pages from the `gh-pages` branch (or configure Pages to use the workflow artifact). The frontend workflow publishes `frontend/`.

Before going live, edit `frontend/js/config.js`:
- set `API_BASE_URL` to your real HTTPS API host
- set `DEMO_MODE` to `false`
- verify the four team profiles and roles

## 2. S3

Create a private bucket with versioning enabled. Example:
```bash
aws s3api create-bucket --bucket tooltruth-deliverables --region ap-south-1 --create-bucket-configuration LocationConstraint=ap-south-1
aws s3api put-bucket-versioning --bucket tooltruth-deliverables --versioning-configuration Status=Enabled
```
Attach a least-privilege IAM policy to the EC2 instance role allowing `s3:PutObject` and `s3:GetObject` only for the deliverables prefix.

## 3. EC2

Recommended starting point: Ubuntu 22.04/24.04, t3.micro or larger.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx git postgresql
sudo mkdir -p /opt/tooltruth
sudo chown -R $USER:$USER /opt/tooltruth
git clone YOUR_REPO_URL /opt/tooltruth
cd /opt/tooltruth/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
python seed_admin.py
```

For production PostgreSQL, set `DATABASE_URL` to your RDS/private Postgres connection. For a small demo, local PostgreSQL on the EC2 host is acceptable.

## 4. Service

```bash
sudo cp tooltruth-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tooltruth-api
sudo systemctl status tooltruth-api
curl http://127.0.0.1:8000/healthz
```

## 5. Nginx

Use the repository file `backend/nginx.conf` as the starting configuration. Copy it to `/etc/nginx/sites-available/tooltruth-api`:
```nginx
server {
    listen 80;
    server_name api.tooltruth.duckdns.org;

    client_max_body_size 25M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable:
```bash
sudo ln -s /etc/nginx/sites-available/tooltruth-api /etc/nginx/sites-enabled/tooltruth-api
sudo nginx -t
sudo systemctl reload nginx
```

## 6. HTTPS

Point the DNS A record / DuckDNS hostname at the EC2 public IP, then:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.tooltruth.duckdns.org
```
Confirm:
```bash
curl https://api.tooltruth.duckdns.org/healthz
```

## 7. GitHub Actions secrets

Backend workflow expects:
- `EC2_HOST`
- `EC2_USER`
- `EC2_SSH_KEY`

The deployment target is `/opt/tooltruth`. The workflow syncs backend files and restarts the systemd service.

Frontend workflow publishes `frontend/` to GitHub Pages. In GitHub repository Settings → Pages, use GitHub Actions as the source.

## 8. CORS

Set `CORS_ORIGINS` to the exact GitHub Pages origin and any custom public website origin. Do not use `*` in production.

## 9. Demo checklist

1. Public homepage loads.
2. Planning v1 opens.
3. Archive displays v1.
4. Admin login succeeds.
5. PDF upload reaches S3.
6. Publish creates a new immutable Version row.
7. Archive can retrieve published metadata.
8. `/healthz` returns `{"status":"ok","service":"tooltruth-api"}`.

## Security notes

- Never commit `.env`.
- Never put AWS secrets in frontend JavaScript.
- Prefer EC2 IAM roles for S3.
- Change the seeded admin password before the public demo.
- Keep the S3 bucket private; serve files with short-lived pre-signed URLs.
- Rotate JWT secret if it is ever exposed.

## 10. PowerPoint upload and in-website viewing

PowerPoint `.ppt` and `.pptx` files are accepted by the admin upload page. During upload the backend keeps the original file and creates a PDF preview with LibreOffice. The public archive opens that PDF in the ToolTruth presentation viewer, so reviewers do not need Microsoft PowerPoint or Google Docs Viewer.

Install LibreOffice on the production API host:
```bash
sudo apt update
sudo apt install -y libreoffice
```

The backend uses `LIBREOFFICE_BIN=libreoffice` by default. If the executable is elsewhere, set the full path in `.env`.

For local storage, set:
```env
LOCAL_STORAGE=true
PUBLIC_API_URL=http://127.0.0.1:8000
```

For production S3 storage, leave `LOCAL_STORAGE=false` and configure the private bucket. The generated PDF preview is stored in S3 alongside the original PowerPoint and is served through a short-lived pre-signed URL.

After publishing a PowerPoint, open **Archive → View presentation**. The presentation is rendered inside the website's viewer page and does not launch PowerPoint.
