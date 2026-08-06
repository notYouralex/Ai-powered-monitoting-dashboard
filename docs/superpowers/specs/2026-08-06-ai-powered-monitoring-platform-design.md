# AI-Powered IT Infrastructure Monitoring Platform — Design

**Date:** 2026-08-06
**Status:** Approved baseline
**Source brief:** `AI_Powered_IT_Infrastructure_Monitoring_ITInternsProject.pdf`

## 1. Goal

Build a centralized, read-only platform that combines Wazuh, Zabbix, Snipe-IT, and Freshservice behind a modular FastAPI application. Grafana provides five dashboards, and a fully local AI assistant explains conditions, correlates evidence, and gives general investigation guidance.

No monitoring, asset, or ticket data may leave the company network. The platform does not execute remediation, change source systems, or create or modify Freshservice tickets.

## 2. Scope

Included:

- Wazuh, Zabbix, Snipe-IT, and read-only Freshservice integrations
- FastAPI, PostgreSQL, Grafana, and a local AI runtime
- Five Grafana dashboards
- Dedicated authenticated AI chat page and compact Grafana AI summaries
- Local administrator-created accounts with one read-only role
- Device correlation, synchronization, caching, audit, and health tracking
- Security hardening, degraded-service behavior, tests, documentation, backup/restore, deployment, and handover

Excluded:

- Automatic ticket creation or updates
- Wazuh active response or Zabbix configuration changes
- Service restarts, remote commands, firewall changes, or Snipe-IT updates
- Cloud AI or external AI fallback
- Public internet exposure
- Full duplication of Wazuh indexes or detailed Zabbix history

## 3. Constraints

- Internship: 350 hours from 2026-07-21, 8 hours/day, 5 days/week; nearly all hours are project time
- Development VM: Ubuntu, 4 CPU cores, about 10 GB RAM, no GPU
- Expected scale: 100–200 devices/assets
- Primary VM: Wazuh all-in-one, Grafana, FastAPI, PostgreSQL, local AI, Freshservice connector
- Other intern VM: Zabbix and Snipe-IT
- Freshservice: SaaS, accessed through a read-only API
- Stable LAN connectivity is assumed
- Final company-server specifications are not yet known

## 4. Architecture

Use a **modular monolith**: one FastAPI codebase with well-bounded modules, deployed as separate API and background-worker processes. PostgreSQL, Grafana, Ollama/local AI, and an internal reverse proxy run alongside it. Wazuh remains outside the project Compose stack because it is already installed.

```text
Grafana dashboards / AI chat
            |
            v
+------------------------------------------+
| FastAPI                                  |
| auth | dashboard API | correlation | AI  |
| Wazuh | Zabbix | Snipe-IT | Freshservice|
+--------------------+---------------------+
                     |
          +----------+----------+
          v                     v
     PostgreSQL           Local AI runtime
```

This approach is selected because it is faster to deliver, easier to test and hand over, and better suited to the VM than microservices.

## 5. FastAPI modules

### Core

Configuration, database connections, HTTP clients, logging, safe errors, request IDs, startup/shutdown, and secret loading.

### Authentication

Administrator-created users, modern password hashing, login/logout, session or token validation, inactivity expiry, account disablement, rate limiting, and login-attempt auditing. All MVP users have the same read-only permissions.

### Integration adapters

Separate Wazuh, Zabbix, Snipe-IT, and Freshservice adapters handle authentication, pagination, timeouts, retries, rate limits, filtering, health checks, and normalization. Source-specific formats do not leak into dashboard or AI modules.

### Normalization

Common internal models include Device, Alert, InfrastructureProblem, Asset, Ticket, IntegrationHealth, and DashboardSummary.

### Device correlation

Canonical device identities use hostnames, IPs, serial numbers, asset tags, source IDs, and manual overrides.

Priority:

1. Manual mapping
2. Exact serial or asset tag
3. Exact normalized hostname
4. Exact stable IP
5. Combined partial evidence

Confidence is high, medium, or low. Low-confidence matches are not auto-merged. Manual mappings are auditable and reversible.

### Synchronization and cache

The worker manages short Wazuh/Zabbix caches, scheduled Snipe-IT/Freshservice syncs, cache expiry, failed-job tracking, retention cleanup, freshness timestamps, and pre-generated Grafana AI summaries. A failed sync never erases the last valid data.

### Dashboard API

Read-only normalized endpoints:

```text
/api/dashboard/executive
/api/dashboard/wazuh
/api/dashboard/zabbix
/api/dashboard/snipe-it
/api/dashboard/freshservice
/api/devices/{device_id}
/api/integrations/health
```

Responses include data timestamps, source freshness, summary values, and degraded-source warnings.

### AI orchestration

The AI module uses internal services to retrieve bounded evidence. It interprets topic/device/time range, defaults to the last 24 hours, builds a structured local-model prompt, validates the result, returns the required answer format, and audits the question and evidence references.

### Audit and observability

Audit logins, AI questions, sync runs, integration failures, manual mappings, and admin account changes. Never log credentials, authorization headers, password hashes, connection strings, or unnecessary raw sensitive content.

## 6. Data strategy and PostgreSQL

### Wazuh and Zabbix

- Query source APIs with bounded filters and time ranges
- Cache common dashboard requests for 30–60 seconds
- Return the last successful cache with a stale warning during temporary failure
- Do not continuously copy full alert or metric history into PostgreSQL

### Snipe-IT and Freshservice

- Synchronize every 5–15 minutes; Snipe-IT defaults to 10–15 minutes
- Upsert by stable source IDs
- Use pagination and incremental sync where supported
- Failed or partial runs do not trigger mass deletion/deactivation
- Freshservice remains strictly read-only

### Core tables

`users`: username, password hash, active state, timestamps, last login.
`devices`: canonical name, hostname, IP, serial, asset tag, OS, type, location, correlation confidence.
`device_source_links`: device, source, source record ID, source identifiers, match method/confidence, manual-override flag, last seen. The source + source-record pair is unique.
`assets`: normalized Snipe-IT reporting fields, device link, assignment, status, model, location, purchase and warranty data.
`tickets`: normalized Freshservice reporting fields, device link, subject, status, priority, category, assignment, source timestamps, due/resolution, SLA state.
`sync_runs`: source, sync type, timing, status, record counts, failure summary.
`integration_status`: health state, last check/success, response time, last error, freshness.
`cache_entries`: key, source, temporary JSON payload, creation and expiry timestamps.

Health states: `healthy`, `degraded`, `unavailable`, `not_configured`.

Retention baseline:

- Assets: current and inactive history
- Freshservice tickets: synchronized reporting history
- Wazuh/Zabbix cache: minutes or hours
- Sync logs: 90 days
- Auth/AI audit: project duration, subject to company policy

## 7. Grafana dashboards

The layouts are approved as an initial baseline. Panel order, labels, metrics, thresholds, and visualizations may change after live-data review and stakeholder feedback.

### Executive overview

TV-friendly, large text, minimal controls, automatic refresh, and no raw sensitive logs. Shows overall health, critical security alerts, unavailable hosts, high-priority tickets, operational trend, top risks, integration health/freshness, and a compact AI summary.

### Wazuh security

Critical/high alerts, severity distribution, active/disconnected agents, top affected devices, trend, and AI security summary.

### Zabbix infrastructure

Host availability, active problems, CPU/memory/disk pressure, trend, top affected hosts, and AI infrastructure summary.

### Snipe-IT assets

Inventory totals, deployment/assignment state, categories, missing identifiers, warranty exposure, and AI asset summary.

### Freshservice service management

Open/high-priority tickets, status/category distribution, SLA risk, resolution trends, linked device issues, and AI ITSM summary.

## 8. AI assistant

Interfaces:

- Dedicated authenticated chat page for detailed investigations
- Compact Grafana summary panel generated by the worker at a controlled interval

Supported question categories:

1. Overall environment summaries
2. Cross-system investigation of a selected device
3. Wazuh alert explanation and recommendations
4. Asset and Freshservice ticket queries

The orchestration layer sends only relevant bounded evidence. Large logs are summarized or truncated. Every detailed answer includes:

- Exact analyzed time range
- Summary
- Most likely explanation, labeled as a hypothesis when unconfirmed
- Possible contributing causes
- Supporting evidence
- Operational impact
- General investigation guidance
- Confidence level
- Missing-source or stale-data warnings

Confidence is rule-assisted:

- **High:** multiple current sources agree and identifiers match reliably
- **Medium:** likely explanation with a missing confirming signal
- **Low:** limited, stale, conflicting, or indirect evidence

With insufficient evidence, the assistant may still state the most likely explanation, but only as a low-confidence hypothesis with validation checks. It does not generate device-specific commands or execute actions.

## 9. Security and degraded operation

- Internal company-network access only
- HTTPS through an internal reverse proxy in final deployment
- Secrets in environment variables or protected files excluded from Git
- Read-only source API accounts where supported
- PostgreSQL exposed only to required services
- Safe errors without stack traces or secrets
- Separate Grafana/service accounts in final deployment
- Executive dashboards exclude unnecessary personal and raw security data
- Monitoring records and ticket text are untrusted input; embedded instructions are not followed by the model

Adapters use timeouts, bounded retries with exponential backoff, rate-limit handling, temporary suspension after repeated failures, and last-success tracking. One failed source does not break unrelated responses.

When a source fails:

- Other panels remain available
- Affected panels show unavailable/degraded/stale status
- Last successful timestamp is visible
- Cached data is explicitly marked stale
- Executive health cannot appear fully healthy
- The AI names missing evidence and lowers confidence
- If the model is unavailable, the API returns a service error rather than fabricating an answer

Standard error shape:

```json
{"error":{"code":"SOURCE_UNAVAILABLE","message":"Zabbix is temporarily unavailable.","source":"zabbix","retryable":true,"request_id":"..."}}
```

## 10. Deployment and resources

Docker Compose services where practical:

```text
fastapi-api
background-worker
postgresql
grafana
ollama
reverse-proxy
```

Deployment sequence: prepare Ubuntu, configure stable internal addressing, install runtime, configure secrets, start PostgreSQL and migrations, start API/worker, test adapters, start local AI, provision Grafana, configure HTTPS, run acceptance tests, and record the final state.

Development resource controls:

- Quantized 3B–4B model
- One model request at a time by default
- Strict evidence/token limits
- Short dashboard caches
- Conservative PostgreSQL settings
- Log rotation and retention cleanup
- Health checks for disk, memory, worker, connectors, database, and model
- Model unload after inactivity where supported
- Provider abstraction for a larger local production model later

## 11. Testing and acceptance

Unit tests cover normalization, correlation, confidence, time parsing, cache expiry, upserts, authentication, evidence packages, and degraded warnings.

Integration tests cover read-only source authentication/retrieval, PostgreSQL migrations/transactions, and local-model structured output. Automated tests mock external services; safe smoke tests may use real read-only credentials.

End-to-end scenarios:

1. Grafana receives normalized live data through FastAPI
2. Snipe-IT and Freshservice sync into PostgreSQL
3. A device correlates across at least two sources
4. AI investigates a device using cross-system evidence
5. A source outage produces stale warnings without breaking unrelated dashboards
6. Invalid login attempts are rejected and audited
7. Backup and restore recover the database and dashboards

Completion requires:

- Five working dashboards with visible timestamps/freshness
- Wazuh/Zabbix refresh in 30–60 seconds
- Snipe-IT/Freshservice sync in 5–15 minutes
- All four AI question categories
- Time range and confidence in every AI answer
- Explicit missing/stale evidence warnings
- No source-system writes and no data leaving the network
- Authentication, auditing, backup, restoration, documentation, and handover demonstrated
- At least one successful restoration test

## 12. Documentation and handover

Deliver architecture, installation, configuration, API, administrator, user, troubleshooting, testing, security, backup/restore, and handover documentation.

Back up PostgreSQL, Grafana provisioning/dashboard files, device mappings, deployment files, configuration templates, and local-model configuration. Secrets use a separate company-approved secure process.

## 13. Delivery sequence

1. Foundation, deployment structure, PostgreSQL, authentication
2. Wazuh and Zabbix adapters and endpoints
3. Snipe-IT and Freshservice synchronization
4. Device correlation
5. Five Grafana dashboards
6. Local AI assistant and Grafana summaries
7. Security hardening and degraded behavior
8. End-to-end testing
9. Documentation, restoration test, deployment, and handover

## 14. Change policy

The architecture, local-data rule, read-only boundary, integrations, and completion requirements remain fixed unless explicitly re-approved. Dashboard panels may evolve without redesign unless changes affect data contracts, security boundaries, or project scope.
