# Backend end-to-end acceptance

This runbook is the backend acceptance checklist for the monitoring platform. It verifies the application, PostgreSQL migration state, authentication boundary, integration behavior, local AI status, network exposure, and backup readiness without changing Wazuh, Zabbix, Snipe-IT, or Freshservice data.

The source integrations are read-only by design. Acceptance must never create a Wazuh active response, modify Zabbix configuration, update Snipe-IT assets, or change Freshservice tickets.

## Acceptance outcomes

Use one of these outcomes for each check:

- **PASS** — observed behavior matches the expected result.
- **PASS WITH CONDITION** — behavior is intentionally degraded/not configured and the reason is documented.
- **FAIL** — expected behavior is missing, inconsistent, insecure, or unexplained.
- **NOT RUN** — the check requires a deployment stage or approval that has not occurred yet.

Do not mark a check PASS based only on an assumption or an earlier environment.

## 1. Record the release candidate

Record the exact Git state before testing:

```bash
git status --short --branch
git rev-parse HEAD
```

The release candidate must contain only intended changes. Untracked local operator files must not be accidentally included in the release.

## 2. Static and configuration validation

Run the normal repository validation from the release candidate:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m flake8 app tests
.venv/bin/python -m compileall -q app
git diff --check
docker compose config --quiet
```

All required checks must pass before release acceptance continues.

## 3. Runtime service state

Inspect the Compose services:

```bash
docker compose ps
```

Expected backend services are:

- PostgreSQL running and healthy;
- FastAPI running and healthy;
- background worker running without a restart loop.

A container repeatedly restarting or an unhealthy PostgreSQL/FastAPI service is a FAIL.

## 4. Migration consistency

Verify the repository has one intended Alembic head and the running application database is at that head:

```bash
.venv/bin/alembic heads
docker compose exec -T fastapi-api alembic current
```

Acceptance requires one expected head and `alembic current` to match it. Do not hard-code an old revision number in the checklist; compare the actual release candidate to the actual running database.

Multiple unexpected heads or a database behind/ahead of the release candidate is a FAIL until explained and approved.

## 5. Basic API health

The process health endpoint is unauthenticated and must return HTTP 200:

```text
GET /health
```

From the host, the development/internal backend check is:

```bash
curl --fail --show-error http://127.0.0.1:8000/health
```

Use the configured `APP_PORT` if it differs from `8000`. Before the final reverse-proxy cutover, FastAPI must remain loopback-only.

## 6. Browser authentication acceptance

Use a normal test/operator account through the browser or another approved interactive client. Do not put a password on a command line.

Verify:

1. valid login succeeds;
2. `GET /api/auth/me` reports the authenticated user;
3. an unauthenticated dashboard request is rejected;
4. a non-admin user cannot perform administrator-only user creation;
5. logout revokes the current session;
6. production browser sessions use a `Secure` cookie after HTTPS deployment.

Authentication errors must not expose password hashes, session tokens, stack traces, source credentials, or internal secret values.

## 7. Dashboard-service access

Grafana uses the configured read-only `GRAFANA_API_TOKEN`. Never print or commit its value. For a command-line acceptance check, read it interactively into a temporary shell variable instead of placing it in shell history:

```bash
read -r -s -p 'Grafana API token: ' GRAFANA_API_TOKEN
echo
AUTH_HEADER="Authorization: Bearer $GRAFANA_API_TOKEN"
```

Then test the canonical backend routes as appropriate for the configured environment:

```text
GET /api/dashboard/executive
GET /api/dashboard/wazuh
GET /api/dashboard/zabbix
GET /api/dashboard/snipe-it
GET /api/dashboard/freshservice
GET /api/integrations/health
GET /api/ai/status
```

For example:

```bash
curl --fail --show-error -H "$AUTH_HEADER" \
  http://127.0.0.1:8000/api/dashboard/executive > /dev/null

curl --fail --show-error -H "$AUTH_HEADER" \
  http://127.0.0.1:8000/api/integrations/health > /dev/null

curl --fail --show-error -H "$AUTH_HEADER" \
  http://127.0.0.1:8000/api/ai/status > /dev/null
```

Immediately remove the temporary token variables when command-line checks are finished:

```bash
unset AUTH_HEADER GRAFANA_API_TOKEN
```

Do not save bearer tokens in scripts, screenshots, terminal transcripts, dashboard JSON, or acceptance records.

## 8. Integration health acceptance

`GET /api/integrations/health` must return a controlled record for each canonical source. Valid source states are:

- `healthy`;
- `degraded`;
- `unavailable`;
- `not_configured`.

A source does not have to be `healthy` to pass release acceptance if the condition is expected and explicitly documented. For example, a source intentionally not configured on a test environment may be **PASS WITH CONDITION**.

For synchronized/cached sources, verify the response includes meaningful freshness/last-success information. A stale source must be identified as stale/degraded rather than silently presented as current.

Unexpected authentication failures, malformed upstream responses, raw exceptions, or one failed source breaking unrelated source summaries are FAIL conditions.

## 9. Source dashboard acceptance

Validate each configured source against its canonical backend response:

### Wazuh

```text
GET /api/dashboard/wazuh
```

When Wazuh is configured and reachable, confirm normalized agent/security data is returned. The acceptance activity is read-only and must not trigger Wazuh active response or change manager/indexer state.

### Zabbix

```text
GET /api/dashboard/zabbix
```

Confirm the latest normalized cache is returned and freshness/warnings agree with integration health. Temporary source failure may preserve a stale snapshot, but the response must identify the degraded/stale condition.

### Snipe-IT

```text
GET /api/dashboard/snipe-it
```

Confirm synchronized asset metrics are available. The test must not update assets, assignments, tags, or source records.

### Freshservice

```text
GET /api/dashboard/freshservice
```

Confirm synchronized ticket/SLA metrics are available. The test must not modify or comment on tickets through Freshservice.

If an unavailable/not-configured source intentionally returns a controlled non-2xx response on its source dashboard route, record that together with the matching integration-health state instead of treating any non-2xx response as automatically acceptable.

## 10. Executive isolation behavior

```text
GET /api/dashboard/executive
```

Confirm the Executive response aggregates normalized source summaries rather than failing completely because one integration is degraded, unavailable, or not configured. Source-specific warnings must remain bounded and must not expose credentials or raw upstream payloads.

## 11. Local AI acceptance

```text
GET /api/ai/status
```

If AI is intentionally disabled, the API must report that controlled state rather than failing the application. If AI is enabled for the release candidate, verify the configured local runtime/models are available before performing investigation/summary quality checks.

AI acceptance must not send monitoring evidence to a cloud service and must not execute remediation commands.

If an endpoint that exists in the release-candidate repository returns HTTP 404, compare the registered routes inside the running FastAPI container with the repository before changing application logic. A missing release-candidate route in the running container indicates a stale/mixed-version image or incomplete service recreation and is a FAIL until the runtime is rebuilt/recreated from the intended release.

## 12. Background worker evidence

Inspect recent worker logs for controlled source/database failures and restart loops:

```bash
docker compose logs --since 15m background-worker
```

Expected behavior:

- configured Freshservice/Snipe-IT synchronization and Zabbix refresh continue on their schedules;
- Wazuh correlation polling continues when configured;
- one source failure does not terminate the other loops;
- logs do not expose API tokens, passwords, authorization headers, private keys, or full connection strings.

If an integration is intentionally unavailable, record the controlled warning and verify the worker remains running.

## 13. Network exposure

Inspect TCP listeners:

```bash
ss -ltn
```

Before final HTTPS deployment, PostgreSQL and FastAPI must remain loopback-only according to the current Compose model. Grafana/Wazuh listener hardening and the final Nginx entry point are validated as part of the approved HTTPS deployment milestone.

After the reverse-proxy deployment, acceptance must verify that backend ports are not directly reachable from another client machine and that only the approved internal HTTPS entry point is exposed.

Unexpected `0.0.0.0` or `[::]` listeners for application-owned backend ports are a FAIL unless the deployment design explicitly requires and approves them.

## 14. Backup readiness

Follow `docs/deployment/postgresql-backup-restore.md`.

At minimum, before production acceptance:

- create a protected custom-format backup;
- verify its SHA-256 checksum;
- verify `pg_restore --list` can read it;
- record the Git revision and migration head/current state;
- complete a restore rehearsal on an isolated non-production PostgreSQL 16 instance.

A backup file that has never been validated is not sufficient recovery evidence.

## 15. Acceptance record

Record the following without secrets:

```text
Date/time (UTC):
Release Git commit:
Compose config validation: PASS/FAIL
Full test suite: PASS/FAIL
Alembic head:
Alembic current:
PostgreSQL health: PASS/FAIL
FastAPI /health: PASS/FAIL
Authentication: PASS/FAIL
Wazuh: PASS / PASS WITH CONDITION / FAIL / NOT RUN
Zabbix: PASS / PASS WITH CONDITION / FAIL / NOT RUN
Snipe-IT: PASS / PASS WITH CONDITION / FAIL / NOT RUN
Freshservice: PASS / PASS WITH CONDITION / FAIL / NOT RUN
Executive: PASS/FAIL
AI: PASS / PASS WITH CONDITION / FAIL / NOT RUN
Worker: PASS/FAIL
Network exposure: PASS / PASS WITH CONDITION / FAIL / NOT RUN
Backup checksum validated: PASS/FAIL
Restore rehearsal: PASS/FAIL/NOT RUN
Reviewer:
Notes/approved conditions:
```

## Release blockers

Do not approve the backend release when any of these remain unexplained:

- required tests fail;
- Compose configuration is invalid;
- PostgreSQL/FastAPI are unhealthy;
- Alembic has unexpected multiple heads;
- the running database revision does not match the intended release;
- authentication or authorization is bypassed;
- credentials/secrets are exposed;
- source integration activity is not read-only;
- a single integration failure breaks unrelated source behavior;
- stale data is presented as fresh;
- worker restart loops occur;
- unexpected backend services are exposed broadly;
- the selected backup fails checksum/archive validation;
- required restore rehearsal has not passed before production acceptance.

Checks that depend on the company-server deployment can remain **NOT RUN** during repository preparation, but they must be completed with runtime evidence before the production release is declared accepted.
