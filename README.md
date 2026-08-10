# AI-Powered Monitoring Dashboard

Centralized internal monitoring platform for Wazuh, Zabbix, Snipe-IT, Freshservice, Grafana, and a fully local AI assistant.

## Current foundation

The repository currently provides the shared platform and integration foundation:

- FastAPI application and health endpoint
- PostgreSQL persistence with Alembic migrations
- Local Argon2id user accounts
- Server-side opaque sessions; only SHA-256 token digests are stored
- Login throttling and authentication audit records
- Administrator-only user creation and bootstrap-admin CLI
- Docker/Compose development scaffold
- Source-prefixed optional configuration for Wazuh, Zabbix, Snipe-IT, and Freshservice
- Request IDs, controlled source errors, and bounded shared HTTP transport
- Empty source-owned integration router/package boundaries for parallel development

Source-specific API clients, authentication flows, functional integration endpoints, Grafana dashboards, synchronization workers, correlation, and local-AI features are not implemented yet. All source integrations remain read-only by design.

## Requirements

- Python 3.12+
- `uv`
- Docker Engine with Docker Compose
- Git

## Python development setup

Create or synchronize the project-local environment from the committed lockfile:

```bash
uv sync --extra dev --frozen
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

Also replace `POSTGRES_PASSWORD` with a strong unique password. The example values are placeholders only. Source settings use the `WAZUH_`, `ZABBIX_`, `SNIPE_IT_`, and `FRESHSERVICE_` prefixes from `.env.example`; a source with missing endpoint or credentials remains `not_configured` and does not prevent FastAPI from starting. TLS verification defaults to enabled. In production, set `APP_ENV=production`, enable `COOKIE_SECURE=true`, and provide secrets through the company-approved protected secret process.

## Docker Compose development

Validate the resolved Compose configuration before starting services:

```bash
docker compose config
```

Build and start the foundation services:

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

## Current API

- `GET /health` — process health
- `POST /api/auth/login` — local account login
- `POST /api/auth/logout` — revoke current server-side session
- `GET /api/auth/me` — current account information
- `POST /api/admin/users` — create a local account; administrator required

## Security boundary

This platform is designed for internal company-network use only. Do not expose the development port directly to the public internet. Final deployment requires HTTPS through the internal reverse proxy. Credentials, password hashes, raw session tokens, authorization headers, and connection strings must not be logged. Monitoring/source-system integrations remain read-only, and no monitoring, asset, ticket, or AI evidence data may leave the company network.
