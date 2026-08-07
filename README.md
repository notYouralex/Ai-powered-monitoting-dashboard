# AI-Powered Monitoring Dashboard

Centralized internal monitoring platform for Wazuh, Zabbix, Snipe-IT, Freshservice, Grafana, and a fully local AI assistant.

## Phase 1 foundation

This branch implements the project foundation only:

- FastAPI application and health endpoint
- PostgreSQL persistence with Alembic migrations
- Local Argon2id user accounts
- Server-side opaque sessions; only SHA-256 token digests are stored
- Login throttling and authentication audit records
- Administrator-only user creation and bootstrap-admin CLI
- Docker/Compose development scaffold

Wazuh, Zabbix, Snipe-IT, Freshservice, Grafana, and local-AI integrations are later delivery phases. Phase 1 does not write to any source system.

## Requirements

- Python 3.12+
- `uv`
- Docker Engine with Docker Compose
- Git

## Python development setup

Create the project-local environment and install development dependencies:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e '.[dev]'
```

Run the test suite:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app
```

## Configuration

Copy the example file; never commit the resulting `.env` file:

```bash
cp .env.example .env
```

Generate a random application secret and place it in `APP_SECRET_KEY`:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Also replace `POSTGRES_PASSWORD` with a strong unique password. The example values are placeholders only. In production, set `APP_ENV=production`, enable `COOKIE_SECURE=true`, and provide secrets through the company-approved protected secret process.

## Docker Compose development

Validate the resolved Compose configuration before starting services:

```bash
docker compose config
```

Build and start the Phase 1 services:

```bash
docker compose build
docker compose up -d postgresql fastapi-api
```

The API is intentionally bound to `127.0.0.1:8000` by default, not every host interface. The container entrypoint runs `alembic upgrade head` before Uvicorn starts.

Create the first administrator interactively after the database is available:

```bash
docker compose exec fastapi-api python -m app.cli create-admin --username admin
```

The password is requested with a hidden prompt. There is deliberately no `--password` command-line option.

## Phase 1 API

- `GET /health` — process health
- `POST /api/auth/login` — local account login
- `POST /api/auth/logout` — revoke current server-side session
- `GET /api/auth/me` — current account information
- `POST /api/admin/users` — create a local account; administrator required

## Security boundary

This platform is designed for internal company-network use only. Do not expose the development port directly to the public internet. Final deployment requires HTTPS through the internal reverse proxy. Credentials, password hashes, raw session tokens, authorization headers, and connection strings must not be logged. Monitoring/source-system integrations remain read-only, and no monitoring, asset, ticket, or AI evidence data may leave the company network.
