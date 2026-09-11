# AI-Powered Monitoring Dashboard

Centralized, read-only IT monitoring platform that brings security, infrastructure, asset, and service-management data into one internal application.

The approved platform combines **Wazuh**, **Zabbix**, **Snipe-IT**, and **Freshservice** behind a modular **FastAPI** backend. **PostgreSQL** stores synchronized and shared application data, the existing host-installed **Grafana** provides the operational dashboards, and a fully local AI assistant provides bounded cross-source summaries and investigation guidance.

No monitoring, asset, ticket, or AI evidence data is intended to leave the company network. Source integrations are read-only by design: the platform observes and explains conditions but does not execute remediation or modify source systems.

## Project context

The project is being developed as a modular monolith for an internal IT environment. FastAPI is the normalization and application boundary between the source systems and presentation layers.

```text
Wazuh -----------+
Zabbix ----------+
Snipe-IT --------+----> FastAPI / normalized contracts ----> Grafana dashboards
Freshservice ----+                 |                         Executive view
                                  v                         Local AI assistant
                              PostgreSQL
```

The architecture separates responsibilities intentionally:

- **Source integrations** handle source-specific authentication, retrieval, pagination, retries, rate limits, and normalization.
- **FastAPI** owns canonical business meanings and normalized dashboard contracts.
- **PostgreSQL** stores application state and synchronized reporting data where appropriate.
- **Grafana** owns presentation and dashboard layout; it must not redefine backend business rules.
- **Executive aggregation** consumes normalized source summaries rather than raw source API responses.
- **Local AI** consumes bounded normalized evidence and remains inside the company network.

The platform is designed for degraded operation. A failed, stale, unavailable, or unconfigured source should not prevent unrelated integrations from continuing to return valid data.

## Current implementation status

The repository currently contains the shared platform foundation plus functional read-only integrations for Wazuh, Freshservice, Zabbix, and Snipe-IT.

| Area | Current status |
|---|---|
| FastAPI application | Implemented |
| PostgreSQL persistence | Implemented |
| Alembic migrations | Implemented |
| Local authentication and admin management | Implemented |
| Wazuh manager integration | Implemented, read-only |
| Wazuh indexer alert integration | Implemented, read-only |
| Wazuh dashboard API | Implemented |
| Wazuh normalized Executive source summary | Implemented internally |
| Freshservice API integration | Implemented, read-only |
| Freshservice background synchronization | Implemented |
| Freshservice dashboard API | Implemented |
| Freshservice normalized Executive source summary | Implemented internally |
| Zabbix API integration and normalized cache refresh | Implemented, read-only |
| Zabbix dashboard API | Implemented |
| Zabbix normalized Executive source summary | Implemented internally |
| Snipe-IT API integration and asset synchronization | Implemented, read-only |
| Snipe-IT dashboard API | Implemented |
| Snipe-IT normalized Executive source summary | Implemented internally |
| Shared Executive aggregator/API | Implemented |
| Host-installed Grafana integration | Implemented using a secured Infinity datasource |
| Default source Grafana dashboards | Implemented for Wazuh, Freshservice, Zabbix, and Snipe-IT |
| Executive Grafana dashboard | Implemented |
| AI Monitoring Summary Grafana dashboard | Implemented |
| Device correlation | Implemented internally for Wazuh, Zabbix, and Snipe-IT observations |
| Cross-source integration health aggregation | Implemented |
| Local AI assistant | Implemented as an optional local Ollama-backed feature |
| Reverse proxy/final HTTPS deployment | Repository template/runbook prepared; live activation and runtime validation pending |

The currently implemented application foundation includes:

- FastAPI application and `/health` endpoint
- PostgreSQL persistence with Alembic migrations
- Local Argon2id user accounts
- Server-side opaque sessions; only SHA-256 session-token digests are stored
- Login throttling and authentication audit records
- Administrator-only user creation and bootstrap-admin CLI
- Docker Compose development services for PostgreSQL, FastAPI, and the background worker
- Background synchronization for Freshservice and Snipe-IT, normalized Zabbix cache refresh, and automatic Wazuh/Zabbix/Snipe-IT device-correlation ingestion
- Source-prefixed optional configuration for Wazuh, Zabbix, Snipe-IT, and Freshservice
- Request IDs, controlled source errors, and bounded shared HTTP transport
- Shared integration-health and Executive source-summary contracts
- Source-owned integration boundaries for parallel development

## Integration architecture

Source-specific API formats stop inside their integration packages. Shared dashboards, Executive aggregation, correlation, and AI orchestration consume normalized contracts rather than raw source responses.

```text
Source API
   |
   v
Source adapter/client
   |
   v
Source service / normalization
   |
   +----> Source dashboard response
   |
   +----> ExecutiveSourceSummary
                 |
                 v
          Executive aggregator
```

This boundary allows each source integration to evolve independently while keeping shared consumers stable.

## Wazuh integration

The Wazuh integration is functional and strictly read-only.

When the Wazuh manager API and Wazuh indexer settings are configured, the authenticated Wazuh dashboard endpoint combines:

- normalized Wazuh agent state from the manager API;
- security alerts from the Wazuh indexer;
- severity totals;
- top affected agents;
- alert trends;
- recent alert data;
- source health and observation timestamps.

The endpoint defaults to a 24-hour alert range, accepts timezone-aware `from` and `to` parameters, and limits requests to a maximum 30-day range.

Wazuh also provides a normalized `ExecutiveSourceSummary` internally. It exposes bounded Executive metrics such as total/active/disconnected agents and total/high/critical alerts, and the shared Executive API combines that summary with the other source summaries.

The integration does not execute Wazuh active response or modify manager/indexer state.

## Freshservice integration

The Freshservice integration is functional and strictly read-only.

When `FRESHSERVICE_BASE_URL` and `FRESHSERVICE_API_KEY` are configured, the background worker retrieves Freshservice API v2 tickets and synchronizes normalized reporting records into PostgreSQL.

Synchronization behavior includes:

- first-run historical backfill;
- incremental synchronization after a successful initial run;
- pagination;
- bounded retry and rate-limit handling;
- overlap protection to reduce missed updates;
- sync-run history;
- preservation of the last valid synchronized data after source failures.

The Freshservice dashboard endpoint reads PostgreSQL rather than calling Freshservice during each dashboard request. Its current normalized data supports:

- Open, Pending, Resolved, and Closed ticket counts;
- Due Today and Overdue operational metrics;
- high-priority and escalated active-ticket metrics;
- all-ticket status distribution;
- unresolved-ticket status distribution;
- unresolved-ticket priority distribution;
- category distribution;
- recent resolution trend;
- recent ticket records;
- integration health, freshness, and warnings.

Freshservice also provides a normalized `ExecutiveSourceSummary` consumed by the shared Executive aggregator.

## Zabbix integration

The Zabbix integration is functional and strictly read-only.

When `ZABBIX_BASE_URL` and `ZABBIX_API_TOKEN` are configured, the background worker retrieves normalized infrastructure data through the Zabbix API and stores the latest validated dashboard snapshot in PostgreSQL. Dashboard requests read that cache so temporary source failures can preserve the last successful snapshot and expose degraded/stale health instead of discarding useful data.

The normalized Zabbix dashboard currently includes host and interface availability, active problems and severity, resource-pressure coverage and trends, top affected hosts, network topology maps, freshness, and warnings. Zabbix also provides a bounded normalized `ExecutiveSourceSummary` consumed by the shared Executive aggregator.

The integration performs read-only Zabbix API operations and does not change hosts, items, triggers, configuration, or monitoring state.

## Snipe-IT integration

The Snipe-IT integration is functional and strictly read-only.

When `SNIPE_IT_BASE_URL` and `SNIPE_IT_API_TOKEN` are configured, the background worker synchronizes normalized hardware asset records into PostgreSQL. The dashboard API reads the synchronized local asset store and exposes totals for assigned/unassigned assets, missing serials or asset tags, warranty state, status/category/location distributions, freshness, and warnings without exposing assignee names.

Snipe-IT also provides a bounded normalized `ExecutiveSourceSummary` consumed by the shared Executive aggregator. The integration reads source data only and does not update Snipe-IT assets or assignments.

## Executive dashboard direction

The Executive dashboard is a shared aggregation layer, not a raw-source parser.

Each integration owner provides a bounded normalized `ExecutiveSourceSummary`. The implemented Executive service combines those source summaries and tolerates individual source failures or stale data without breaking unrelated results.

Current source-summary status:

- Wazuh: implemented
- Freshservice: implemented
- Zabbix: implemented
- Snipe-IT: implemented
- Shared Executive aggregation endpoint: implemented at `GET /api/dashboard/executive`
- Executive Grafana dashboard: implemented in `grafana/dashboards/executive.json`

## Grafana dashboard model

The project reuses the existing host-installed Grafana instead of starting a second Grafana container in Compose. The repository contains six source-controlled dashboard templates under `grafana/dashboards/`: Wazuh, Freshservice, Zabbix, Snipe-IT, Executive, and AI Monitoring Summary.

The current deployment uses one manually configured Infinity datasource named `Monitoring API` that points to the loopback FastAPI service and stores `GRAFANA_API_TOKEN` in Grafana's secure datasource configuration. Dashboard JSON does not contain the bearer token. The authoritative setup and import workflow is documented in `grafana/README.md`.

The generic datasource and dashboard provisioning files are intentionally inert for this host-installed deployment. Zabbix-specific provisioning templates also remain in the repository as reference assets, but the current operational workflow is manual datasource configuration and dashboard import through the existing Grafana instance.

The project provides project-maintained default source, Executive, and AI summary dashboards while allowing authorized users to customize presentation. The Executive dashboard consumes only the implemented shared Executive API.

The governing rule is:

> **FastAPI defines what a metric means. Grafana defines how that metric is displayed.**

Users may rearrange panels, change appropriate visualization types, adjust thresholds and display options, hide panels, and create team/user-specific dashboard copies. Canonical backend metric definitions should not be recreated or changed independently in Grafana.

See `docs/development/dashboard-flexibility.md` for the detailed flexibility guidelines.

## Collaboration and ownership

The repository is designed for parallel development by two integration owners while shared architecture remains coordinated.

- Intern A owns Wazuh and Freshservice integration code, tests, and source dashboards.
- Intern B owns Zabbix and Snipe-IT integration code, tests, and source dashboards.
- Shared contracts, Executive aggregation, core/database architecture, correlation, migrations, deployment, and cross-source AI behavior are shared responsibilities.

Cross-source consumers should depend on normalized contracts instead of source-specific response formats.

See `docs/development/collaboration-rules.md` for the complete collaboration rules.

## Current Docker Compose services

The current development Compose stack contains:

```text
postgresql
fastapi-api
background-worker
```

Grafana is intentionally external to this Compose stack because the project reuses the existing host-installed instance. A local AI runtime remains host-local. The repository now includes an internal HTTPS Nginx template under `deploy/nginx/` for Grafana, FastAPI/AI, and Wazuh Dashboard. Nginx installation, certificate installation, Grafana/Wazuh Dashboard listener changes, DNS/firewall work, and service reloads remain separate deployment actions.

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

Also replace `POSTGRES_PASSWORD` with a strong unique password. The example values are placeholders only.

Source settings use the `WAZUH_`, `ZABBIX_`, `SNIPE_IT_`, and `FRESHSERVICE_` prefixes from `.env.example`. A source with missing required configuration remains `not_configured` and must not prevent FastAPI from starting.

The Wazuh dashboard requires both manager API and indexer settings. TLS verification defaults to enabled. In production, use the company-approved protected secret process, set `APP_ENV=production`, and enable secure cookies through `COOKIE_SECURE=true`.

## Docker Compose development

Validate the resolved Compose configuration before starting services:

```bash
docker compose config
```

Build and start the current application services:

```bash
docker compose build
docker compose up -d postgresql fastapi-api background-worker
```

The API is intentionally bound to `127.0.0.1:8000` by default rather than all host interfaces. The API container entrypoint runs `alembic upgrade head` before Uvicorn starts. The background worker does not run migrations; it periodically synchronizes Freshservice and Snipe-IT, refreshes the normalized Zabbix dashboard cache, correlates successful Snipe-IT/Zabbix observations, and polls configured Wazuh agents for correlation.

The application source is copied into the Docker image during build rather than bind-mounted into the API container. After application-code changes, rebuild/recreate the relevant container before expecting the running API to use the new code.

Create the first administrator interactively after the database is available:

```bash
docker compose exec fastapi-api python -m app.cli create-admin --username admin
```

The password is requested with a hidden prompt. There is deliberately no `--password` command-line option.

## Current API

Currently exposed application endpoints include:

- `GET /health` — process health
- `POST /api/auth/login` — local account login
- `POST /api/auth/logout` — revoke the current server-side session
- `GET /api/auth/me` — current account information
- `POST /api/admin/users` — create a local account; administrator required
- `GET /api/dashboard/wazuh` — authenticated Wazuh agent and security-alert dashboard data
- `GET /api/dashboard/freshservice` — authenticated Freshservice dashboard data from synchronized PostgreSQL records
- `GET /api/dashboard/zabbix` — authenticated Zabbix infrastructure dashboard data from the normalized cache
- `GET /api/dashboard/snipe-it` — authenticated Snipe-IT asset dashboard data from synchronized PostgreSQL records
- `GET /api/dashboard/snipe-it/recent-activity` — authenticated bounded recent Snipe-IT activity
- `GET /api/dashboard/snipe-it/warranty-expiry` — authenticated Snipe-IT warranty-expiry data
- `GET /api/dashboard/executive` — authenticated shared Executive aggregation across the four normalized source summaries
- `GET /api/integrations/health` — authenticated cross-source integration health/freshness aggregation
- `GET /api/ai/status` — local AI readiness/status for dashboard-access clients
- `POST /api/ai/query` — authenticated local AI investigation
- `GET /api/ai/insights/dashboard` — combined cached AI summary for the Grafana AI dashboard
- source-specific AI summaries at `GET /api/ai/insights/executive`, `GET /api/ai/insights/wazuh`, `GET /api/ai/insights/zabbix`, `GET /api/ai/insights/snipe-it`, and `GET /api/ai/insights/freshservice`

Device correlation is currently an internal persistence/worker capability rather than a standalone public API. The browser UI currently exposes the local AI Investigation page at `/ai`; the proposed unified `/app/*` dashboard shell in `docs/development/web-app-implementation-plan.md` has not been implemented.

## Next major milestones

The repository-level implementation is substantially complete. The remaining work is deployment and runtime acceptance rather than the earlier shared-backend milestones:

1. Deploy the approved release to the target internal server and provide environment-specific source configuration through the protected secret process.
2. Activate and validate the prepared internal HTTPS/reverse-proxy model, including the approved Grafana/Wazuh Dashboard listener changes.
3. Run the backend and Grafana acceptance runbooks against the deployed release and record runtime evidence for each configured source.
4. Complete the protected PostgreSQL backup validation and isolated restore rehearsal required for production acceptance.
5. Complete final operational handover and document any accepted environment-specific limitations.
6. Treat the unified `/app/*` web-dashboard migration as a separate planned workstream; it is not part of the completed backend/Grafana foundation and has not been implemented.


## Security boundary

This platform is designed for internal company-network use only.

Do not expose the development API directly to the public internet. Final deployment requires HTTPS through the internal reverse proxy.

Credentials, password hashes, raw session tokens, authorization headers, private keys, connection strings, and other sensitive credential material must not be logged or committed.

Monitoring/source-system integrations remain read-only. The project must not introduce Wazuh active response, Zabbix configuration changes, Snipe-IT updates, Freshservice ticket writes, remote commands, firewall changes, service restarts, cloud AI fallback, or public exposure without explicit architecture approval.

No monitoring, asset, ticket, or AI evidence data may leave the company network.

## Design documentation

The approved baseline architecture is documented in:

- `docs/superpowers/specs/2026-08-06-ai-powered-monitoring-platform-design.md`
- `docs/development/collaboration-rules.md`
- `docs/development/dashboard-flexibility.md`

The design document describes the approved target architecture. This README is intended to describe both that project context and the repository's current implementation state so planned components are not confused with implemented ones.
