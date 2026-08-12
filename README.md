# AI-Powered Monitoring Dashboard

Centralized internal monitoring platform for Wazuh, Zabbix, Snipe-IT, Freshservice, Grafana, and a fully local AI assistant.

## Current implementation

The repository currently provides the shared platform foundation plus functional read-only Wazuh security monitoring and Freshservice ticket pipelines:

- FastAPI application and health endpoint
- PostgreSQL persistence with Alembic migrations
- Local Argon2id user accounts
- Server-side opaque sessions; only SHA-256 token digests are stored
- Login throttling and authentication audit records
- Administrator-only user creation and bootstrap-admin CLI
- Docker/Compose development scaffold with separate API and background-worker processes
- Source-prefixed optional configuration for Wazuh, Zabbix, Snipe-IT, and Freshservice
- Request IDs, controlled source errors, and bounded shared HTTP transport
- Read-only Wazuh manager agent client and Wazuh indexer alert client with bounded source handling
- Authenticated Wazuh dashboard API combining normalized agent and security-alert data
- Read-only Freshservice API v2 ticket client with pagination and bounded retry/rate-limit handling
- Incremental Freshservice synchronization into PostgreSQL with sync-run history and last-valid-data preservation
- Authenticated Freshservice dashboard API built only from synchronized PostgreSQL records
- Source-owned integration package boundaries for Zabbix and Snipe-IT parallel development

Zabbix and Snipe-IT source clients and functional endpoints are not implemented yet. Grafana provisioning/dashboards, Executive aggregation, cross-source correlation, and local-AI features also remain planned work. All source integrations remain read-only by design.

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

Also replace `POSTGRES_PASSWORD` with a strong unique password. The example values are placeholders only. Source settings use the `WAZUH_`, `ZABBIX_`, `SNIPE_IT_`, and `FRESHSERVICE_` prefixes from `.env.example`; a source with missing endpoint or credentials remains `not_configured` and does not prevent FastAPI from starting. The Wazuh dashboard requires both manager API settings and Wazuh indexer settings. TLS verification defaults to enabled. In production, set `APP_ENV=production`, enable `COOKIE_SECURE=true`, and provide secrets through the company-approved protected secret process.

## Docker Compose development

Validate the resolved Compose configuration before starting services:

```bash
docker compose config
```

Build and start the application services:

```bash
docker compose build
docker compose up -d postgresql fastapi-api background-worker
```

The API is intentionally bound to `127.0.0.1:8000` by default, not every host interface. The API container entrypoint runs `alembic upgrade head` before Uvicorn starts. The background worker does not run migrations and periodically synchronizes Freshservice when that integration is configured.

Create the first administrator interactively after the database is available:

```bash
docker compose exec fastapi-api python -m app.cli create-admin --username admin
```

The password is requested with a hidden prompt. There is deliberately no `--password` command-line option.

## Wazuh integration

When the Wazuh manager API and Wazuh indexer settings are both configured, the authenticated Wazuh dashboard endpoint retrieves normalized agent state from the manager API and security alerts from the indexer. The endpoint defaults to a 24-hour alert window, accepts timezone-aware `from` and `to` query parameters, and limits requests to a maximum 30-day range.

The integration is read-only: it authenticates to retrieve manager data and searches indexer alert data, but it does not execute Wazuh active response or modify manager/indexer state.

## Freshservice integration

When `FRESHSERVICE_BASE_URL` and `FRESHSERVICE_API_KEY` are configured, the background worker retrieves Freshservice API v2 tickets through a read-only client and stores normalized ticket records in PostgreSQL. Synchronization is incremental after the first successful run, uses a short overlap window to reduce missed updates, and records synchronization status without deleting the last valid ticket data after a source failure.

The dashboard endpoint reads synchronized PostgreSQL data rather than calling Freshservice during the request. It reports integration health/staleness, ticket totals, status and priority distributions, top categories, a recent resolution trend, overdue/escalated counts, and recent tickets.

## Current API

- `GET /health` — process health
- `POST /api/auth/login` — local account login
- `POST /api/auth/logout` — revoke current server-side session
- `GET /api/auth/me` — current account information
- `POST /api/admin/users` — create a local account; administrator required
- `GET /api/dashboard/wazuh` — authenticated Wazuh agent and security-alert dashboard data
- `GET /api/dashboard/freshservice` — authenticated Freshservice dashboard data from synchronized PostgreSQL records

## Security boundary

This platform is designed for internal company-network use only. Do not expose the development port directly to the public internet. Final deployment requires HTTPS through the internal reverse proxy. Credentials, password hashes, raw session tokens, authorization headers, and connection strings must not be logged. Monitoring/source-system integrations remain read-only, and no monitoring, asset, ticket, or AI evidence data may leave the company network.
