# Grafana operations and handover runbook

This is the operator-facing guide for the project-maintained Grafana dashboards. It is intentionally detailed so a new operator can validate, import, recover, and hand over the dashboards without guessing how the project works.

This document does not authorize live changes. Installing plugins, changing Grafana configuration, replacing certificates, changing DNS/firewall rules, restarting/reloading services, or overwriting a live dashboard requires the normal explicit approval for that action.

## Before you start

Use this runbook only after the backend acceptance checks in `docs/deployment/backend-acceptance.md` are understood. For a new deployment or recovery, do not begin by editing dashboards. First prove that the backend and datasource path are healthy.

You need:

1. Access to the project repository at the release candidate commit.
2. Access to the internal Grafana UI.
3. Permission to view/import dashboards if import work is required.
4. The `Monitoring API` Infinity datasource, or permission to create it.
5. The FastAPI service running on loopback at `http://127.0.0.1:8000` on the Grafana host.
6. The `GRAFANA_API_TOKEN` supplied through the approved secret process. Do not display it, copy it into notes, or paste it into dashboard JSON.
7. The required Grafana plugins already installed, or separate approval to install them.

Before touching Grafana, record:

```text
Release commit: ______________________________
Operator: ___________________________________
Date/time: __________________________________
Grafana version: _____________________________
FastAPI health: PASS / FAIL
Integration health: PASS / FAIL
Dashboard backup/export location: ___________
```

If you cannot identify the release commit, **stop here**. Do not import dashboard files from an unknown branch or working tree.

## Golden rules

These rules are not optional:

- FastAPI defines what a metric means. Grafana controls presentation only.
- Project dashboards consume canonical FastAPI endpoints. Do not reimplement source-specific business logic in Grafana.
- Do not paste `GRAFANA_API_TOKEN`, passwords, private key material, bearer tokens, cookies, or source credentials into JSON, documentation, tickets, chat, screenshots, or Git.
- The token belongs only in Grafana's **secure bearer token field** or another approved secret store.
- Do not disable TLS verification to make a connection work. Fix certificate trust instead.
- Do not commit certificates containing private material or any private key.
- Do not replace a project-maintained dashboard with an ad-hoc UI copy unless the change has been reviewed and exported back to source control intentionally.
- Prefer a separate dashboard copy for team/user layout customization.
- Never install a plugin, restart Grafana, change Grafana configuration, or change file permissions as a troubleshooting shortcut without explicit approval.
- If the backend endpoint is wrong, fix the backend or datasource path. Do not hide the problem by changing metric definitions in Grafana.

## Architecture in one minute

The normal data path is:

```text
Wazuh / Zabbix / Snipe-IT / Freshservice
                  |
                  v
              FastAPI
                  |
                  v
       Monitoring API datasource
                  |
                  v
               Grafana
```

Grafana does not need source-system credentials for the project dashboards. It talks to FastAPI through one Infinity datasource named `Monitoring API`.

The project intentionally leaves files under `grafana/provisioning/` inert in the current host-installed model. They contain empty `datasources: []` or `providers: []` definitions and must not be treated as active production provisioning.

## Known pre-deployment host state

The host observed during repository preparation had:

```text
Grafana:   13.1.1
Grafana:   HTTPS on port 3000
FastAPI:   127.0.0.1:8000
PostgreSQL 127.0.0.1:55432
```

Grafana was listening on:

```text
*:3000
```

That is a **temporary pre-deployment state**. The internal HTTPS deployment runbook changes the final design so direct Grafana access is restricted to loopback behind the approved reverse proxy. Do not use the current broad listener as the target production design.

To check whether your operator account can use the local certificate directly:

```bash
test -r /etc/grafana/cert.crt && echo "certificate readable" || echo "certificate not readable"
```

On the observed host, the normal operator account could **not** read `/etc/grafana/cert.crt` because the file is protected for `root:grafana`. Do not use `chmod`, `chgrp`, or broader permissions merely to make a health check work.

If your authorized operator account can read the certificate, check Grafana health with:

```bash
curl --fail --show-error \
  --cacert /etc/grafana/cert.crt \
  https://localhost:3000/api/health
```

Expected result includes:

```json
"database": "ok"
```

If the certificate is not readable, use the approved trusted external Grafana HTTPS URL after the reverse-proxy deployment, or have an authorized privileged operator perform the local certificate-backed check. Record `NOT RUN - certificate file not readable` rather than weakening file permissions or TLS verification.

If certificate validation fails, do not add an insecure option. Confirm the configured Grafana certificate and hostname instead.

## Dashboard inventory

These six JSON files are the project-maintained defaults:

| Dashboard | File | UID | Refresh | Canonical API |
|---|---|---|---|---|
| Wazuh Security | `grafana/dashboards/wazuh.json` | `monitoring-wazuh` | 30s | `/api/dashboard/wazuh` |
| Zabbix Infrastructure | `grafana/dashboards/zabbix-infrastructure.json` | `monitoring-zabbix` | 30s | `/api/dashboard/zabbix` |
| Snipe-IT Asset Management | `grafana/dashboards/snipe-it.json` | `monitoring-snipe-it` | 1m | `/api/dashboard/snipe-it` plus bounded activity/warranty routes |
| Freshservice Service Management | `grafana/dashboards/freshservice.json` | `monitoring-freshservice` | 1m | `/api/dashboard/freshservice` |
| Executive Overview | `grafana/dashboards/executive.json` | `monitoring-executive` | 1m | `/api/dashboard/executive` |
| AI Monitoring Summary | `grafana/dashboards/ai-summary.json` | `monitoring-ai-summary` | 5m | `/api/ai/insights/dashboard` |

Supporting health endpoint:

```text
/api/integrations/health
```

A slower refresh rate is not automatically a fault. For example, the AI summary refreshes every five minutes, while Wazuh and Zabbix refresh every 30 seconds.

## Monitoring API datasource

The dashboard datasource must be one Infinity datasource with the following logical configuration:

```text
Name:         Monitoring API
Base URL:     http://127.0.0.1:8000
Allowed host: http://127.0.0.1:8000
Authentication: Bearer token
```

Enter the actual `GRAFANA_API_TOKEN` only in Grafana's secure bearer token field.

### Datasource setup checklist

In Grafana:

1. Open **Connections** or **Data sources**.
2. Open the existing `Monitoring API` datasource, or create an Infinity datasource if this is a new deployment.
3. Confirm the base URL is exactly `http://127.0.0.1:8000` for the current host-local architecture.
4. Confirm the allowed host is the same loopback URL.
5. Confirm authentication uses the secure bearer token field.
6. Do not place an Authorization header directly inside dashboard JSON.
7. Use Grafana's datasource test/check action if available.
8. Record only PASS/FAIL in the handover record. Do not record the token value.

If the datasource check fails, **stop here** and diagnose the backend path before importing dashboards.

### Safe backend token test

When you need to prove the service token works without printing it, run this from the repository root while the normal Compose services are running:

```bash
docker compose exec -T fastapi-api python -c '
import os, urllib.request
url="http://127.0.0.1:8000/api/integrations/health"
token=os.environ["GRAFANA_API_TOKEN"]
req=urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
with urllib.request.urlopen(req, timeout=15) as response:
    print("status=", response.status)
'
```

Expected:

```text
status= 200
```

This command reads the token from the running container environment and prints only the HTTP status.

If the result is `401` or `403`, do not generate a random replacement token. Confirm that Grafana and FastAPI are configured with the same approved token.

## Plugin verification

The project dashboards require these external Grafana plugins:

- `yesoreyeram-infinity-datasource` for the `Monitoring API` datasource.
- `tamirsuliman-weathermap-panel` for the Zabbix `Live Host Topology` panel. The source-controlled dashboard currently targets plugin version `1.6.12`.

The current host has shown an active Infinity plugin process. The Zabbix dashboard source requires the WeatherMap plugin whether or not a CLI listing happens to show it.

### Important CLI caveat

On this host:

```bash
grafana cli plugins ls
```

returned:

```text
no installed plugins found
```

while Grafana was actively running plugin processes under `/var/lib/grafana/plugins/`. Therefore this CLI result alone is **not authoritative** for the host-installed service context.

Use at least two pieces of evidence before concluding a plugin is missing:

1. Check Grafana's **Administration / Plugins** UI.
2. Check whether Grafana has a running plugin process:

```bash
ps -eo pid,cmd | grep '/var/lib/grafana/plugins/' | grep -v grep
```

3. If permissions allow, inspect `/var/lib/grafana/plugins/` without changing permissions.
4. Open the dashboard and confirm the expected visualization actually renders.

If a required plugin is genuinely missing, **stop here**. Plugin installation is a system change and requires explicit approval. Do not reinstall plugins merely because `grafana cli plugins ls` returned an empty list.

## Import or restore the project dashboards

### Before overwriting anything

If a dashboard already exists and contains user/team customizations, export a backup from the Grafana UI first. Store that backup in the approved operational backup location, not in the repository unless it has been reviewed for source control.

Record:

```text
Dashboard: _________________________________
Existing UID: ______________________________
Backup exported: YES / NO / NOT APPLICABLE
Backup location: ___________________________
```

If an existing customized dashboard has no backup and the import would overwrite it, **stop here**.

### Recommended import order

Use this order so source dashboards are proven before aggregate/AI views:

1. Wazuh Security
2. Zabbix Infrastructure
3. Snipe-IT Asset Management
4. Freshservice Service Management
5. Executive Overview
6. AI Monitoring Summary

### Import procedure

For each dashboard:

1. In Grafana, open **Dashboards**.
2. Choose **New** then **Import**.
3. Upload the matching JSON file from `grafana/dashboards/`.
4. When Grafana asks for a datasource, select `Monitoring API`.
5. Confirm the imported title and UID match the inventory table above.
6. Import the dashboard.
7. Open it immediately.
8. Confirm panels render without datasource/plugin errors.
9. Confirm the visible data is plausible and fresh before moving to the next dashboard.

Do not import all six dashboards blindly and only check at the end. A failure should be isolated to the first dashboard that does not pass.

## Dashboard-by-dashboard acceptance

The goal is not merely “the page opens.” Each dashboard has a minimum visual acceptance set.

### Wazuh Security

Expected panels:

- Total Alerts
- Critical Alerts
- High Alerts
- Total Vulnerabilities
- Critical Vulnerabilities
- High Vulnerabilities
- Alert Trend
- MITRE Tactics
- Top Alerts
- Vulnerabilities by Severity
- Top Affected Agents
- Agent Status
- Recent Alerts

Acceptance:

1. Dashboard loads without datasource errors.
2. Alert/vulnerability totals are populated when source data exists.
3. Time-range-sensitive panels change when the dashboard time range changes.
4. Recent Alerts is not stuck on an old observation when integration health reports healthy.
5. No panel calls a source system directly.

### Zabbix Infrastructure

Expected panels:

- Hosts
- Problems
- Unreachable
- Avg CPU Usage
- Critical Problems
- Live Host Topology
- System Information
- CPU Load
- Memory Usage
- Warnings
- Network Latency
- Network Bandwidth

Acceptance:

1. Summary stats render.
2. CPU and memory charts render recent data when available.
3. `Live Host Topology` renders using `tamirsuliman-weathermap-panel`.
4. The topology contains the expected host nodes and status coloring.
5. Treat topology line status as the dashboard's logical host/problem representation; it is not proof of physical cable/circuit telemetry.
6. `Warnings` is visible when the backend reports warnings.

If the topology panel says the visualization/plugin is unavailable while other Zabbix panels work, diagnose the WeatherMap plugin before touching the backend.

### Snipe-IT Asset Management

Expected panels:

- Total Assets
- Deployed
- Available
- Maintenance
- Retired
- Assets by Type / Category
- Assets by Status
- Assets by Company
- Recent Activity
- Upcoming Warranty Expiry

Acceptance:

1. Summary asset counts render.
2. Category/status/company distributions render.
3. Recent Activity loads independently of the main asset summary.
4. Warranty expiry data renders when applicable.
5. Dashboard does not expose unnecessary assignee-sensitive data.

### Freshservice Service Management

Expected panels:

- Overdue
- Due Today
- Open Tickets
- Pending Tickets
- Resolved Tickets
- Closed Tickets
- Resolution SLA Compliance
- Unresolved Tickets by Priority
- Unresolved Tickets by Status
- All Tickets by Status
- Resolution Trend
- Recent Tickets
- Historical Resolution SLA Compliance

Acceptance:

1. Current-state ticket panels render.
2. Historical trend panels show the intended six-calendar-month reporting window.
3. SLA values come from the backend contract; do not recreate the SLA formula in Grafana.
4. Recent Tickets data is current enough for the configured synchronization interval.

### Executive Overview

Expected panels:

- Overall Health
- Security Alerts
- Open Tickets
- Overdue Tickets
- SLA Compliance
- Assets
- High-Severity Issues by Domain
- Tickets by Status
- Source Health & Freshness
- Attention Required

Acceptance:

1. All four source health rows appear.
2. `Source Health & Freshness` distinguishes healthy/degraded/unavailable/not-configured state correctly.
3. A single degraded source does not remove unrelated source information.
4. `Overall Health` matches the backend's canonical integration-health meaning.
5. Attention Required is consistent with the API, not a Grafana-only calculation.

### AI Monitoring Summary

Expected panels:

- Executive AI Summary
- Wazuh AI Summary
- Zabbix AI Summary
- Snipe-IT AI Summary
- Freshservice AI Summary

Acceptance:

1. The combined endpoint `/api/ai/insights/dashboard` is reachable.
2. All five sections render through that combined endpoint.
3. Confidence values render in the expected column.
4. AI output remains explanatory/investigative only.
5. No dashboard contains model credentials or source credentials.

A `404` from `/api/ai/status` or `/api/ai/insights/dashboard` when the repository contains AI routes strongly suggests the running FastAPI image is stale relative to the release candidate. Treat that as a release blocker. Do not “fix” the dashboard URL to point somewhere else.

## Verify source health before blaming Grafana

Use the canonical health API through the service token. A healthy Grafana dashboard can still show stale/empty data if its source is degraded.

Check:

```text
/api/integrations/health
```

For each canonical source, review:

- status
- last successful refresh/sync
- stale state
- warnings

Interpretation:

- `healthy`: source path is currently healthy.
- `degraded`: useful data may still be present, but freshness/latest operation has a problem.
- `unavailable`: no usable current source result is available.
- `not_configured`: required source configuration is absent.

Do not import or redesign a dashboard to hide a degraded source.

## Daily operator checks

A normal daily check can be completed without changing anything:

1. Confirm the application containers are up:

```bash
docker compose ps
```

2. Confirm FastAPI health:

```bash
curl --fail --show-error http://127.0.0.1:8000/health
```

Expected:

```json
{"status":"ok"}
```

3. Confirm Grafana health from the approved trusted URL/certificate path.
4. Open Executive Overview.
5. Review `Source Health & Freshness` for all four sources.
6. Open any source dashboard marked degraded or stale.
7. Check the dashboard warning panel/section before assuming Grafana is broken.
8. Confirm Wazuh/Zabbix 30-second dashboards are updating when active data changes.
9. Confirm Freshservice/Snipe-IT freshness matches their synchronization behavior.
10. Review the AI Monitoring Summary only after the normal source dashboards are healthy enough to provide trustworthy evidence.

Record abnormal findings, not credentials.

## Ten-minute post-deployment smoke check

After an approved deployment/cutover, run this order:

```text
1. Reverse-proxy HTTPS entry point reachable
2. Grafana login reachable
3. FastAPI /health = 200
4. Monitoring API datasource test = PASS
5. /api/integrations/health = 200
6. Wazuh dashboard = PASS
7. Zabbix dashboard = PASS
8. Snipe-IT dashboard = PASS
9. Freshservice dashboard = PASS
10. Executive dashboard = PASS
11. AI dashboard = PASS or documented model/runtime blocker
12. Direct backend ports are not remotely exposed
```

If a step fails, stop at that step. Fix the dependency before continuing to downstream dashboards.

## Troubleshooting decision tree

Use this order. Do not skip directly to reinstalling or restarting software.

### A. Grafana page itself does not open

1. Check Grafana service health endpoint.
2. Check the expected listener with `ss -ltn`.
3. Check whether the HTTPS/reverse-proxy deployment is active or still in pre-deployment state.
4. If a service restart/config change appears necessary, **stop here** and obtain explicit approval.

### B. Grafana opens but every project dashboard says no data

1. Check `http://127.0.0.1:8000/health`.
2. Check the `Monitoring API` datasource.
3. Confirm the datasource base URL/allowed host is `http://127.0.0.1:8000` for this host model.
4. Confirm token authentication returns HTTP 200 using the safe token test above.
5. If all endpoints fail authentication, fix the datasource/token configuration; do not modify six dashboards individually.

### C. Only one source dashboard has no data

1. Check `/api/integrations/health` for that source.
2. Call the source's canonical FastAPI endpoint.
3. If the API itself is degraded/unavailable, investigate the integration/worker path.
4. If the API returns correct data but Grafana does not, inspect that dashboard's datasource selection, query path, transformations, and plugin requirements.

### D. Only Zabbix topology is broken

1. Confirm normal Zabbix stats/charts work.
2. Confirm `tamirsuliman-weathermap-panel` is available in the running Grafana UI.
3. Confirm the topology panel is using the project JSON.
4. Do not change backend topology data merely to make a missing plugin error disappear.

### E. Dashboard says unauthorized/forbidden

1. Confirm FastAPI health first.
2. Run the safe service-token status test.
3. Confirm `Monitoring API` has the approved token in its secure field.
4. Confirm no one pasted a token into the dashboard JSON instead.
5. If the token must be rotated, follow the approved secret-rotation process; do not expose the old/new token in terminal screenshots or documentation.

### F. Executive dashboard disagrees with a source dashboard

1. Compare the canonical API responses/health timestamps.
2. Check whether one source is stale.
3. Check dashboard time range.
4. Confirm both dashboards are from the same release candidate.
5. Do not create a Grafana-only formula to force the values to match. The backend owns the business definition.

### G. AI dashboard is missing or returns 404

1. Confirm the repository release candidate includes the AI routes.
2. Confirm the running FastAPI container was rebuilt/recreated from that release candidate.
3. Check `/api/ai/status`.
4. Check local Ollama/model readiness only after the route exists.
5. Treat a missing route in a supposedly current container as a stale/mixed-version image issue.

### H. A dashboard looks visually wrong after import

1. Verify the dashboard title and UID.
2. Confirm it was imported from the release candidate's `grafana/dashboards/` directory.
3. Check plugin availability.
4. Check datasource mapping.
5. Compare with the source-controlled JSON before editing the UI.
6. If the UI dashboard was customized intentionally, preserve the custom copy and restore the canonical project dashboard separately.

## Rollback and recovery

### Recover a project dashboard

The repository JSON is the canonical recovery source for the project-maintained default dashboards.

If a project dashboard is accidentally edited or corrupted:

1. Export any useful current customized version before overwriting it.
2. Confirm the repository is on the approved release commit.
3. Re-import the matching JSON file from `grafana/dashboards/`.
4. Map it to `Monitoring API`.
5. Verify its UID/title.
6. Repeat that dashboard's acceptance checklist above.

### Recover from a bad datasource edit

If the datasource was changed incorrectly:

1. Record the current datasource settings except secrets.
2. Restore the approved base URL/allowed-host settings.
3. Re-enter the approved token only through the secure bearer token field if necessary.
4. Test the datasource.
5. Validate one source dashboard before checking all dashboards.

If recovery requires restarting Grafana or editing live configuration files, **stop here** and obtain explicit approval.

### Preserve user customizations

Do not overwrite a customized dashboard without a backup. Preferred model:

```text
Project default dashboard -> maintained from Git
Team copy                 -> team presentation changes
User copy                 -> personal presentation changes
```

If a user needs a different business definition, that is a backend/product change, not a dashboard-copy customization.

## Handover package

The operator should receive these references:

```text
grafana/README.md
docs/deployment/grafana-operations-handover.md
docs/deployment/backend-acceptance.md
docs/deployment/postgresql-backup-restore.md
docs/deployment/internal-https.md
docs/development/dashboard-flexibility.md
grafana/dashboards/*.json
```

Do not include `.env`, private keys, raw tokens, database dumps containing production data, or credential screenshots in a normal documentation bundle.

## Final handover checklist

Mark each item PASS/FAIL/NOT APPLICABLE and record evidence separately.

```text
[ ] Release commit recorded
[ ] Repository working tree understood/clean for release files
[ ] Full automated tests passed
[ ] Compose configuration validated
[ ] Grafana health = OK
[ ] FastAPI /health = 200
[ ] Monitoring API datasource = PASS
[ ] Infinity datasource plugin available
[ ] WeatherMap plugin available for Zabbix topology
[ ] Wazuh Security accepted
[ ] Zabbix Infrastructure accepted
[ ] Snipe-IT Asset Management accepted
[ ] Freshservice Service Management accepted
[ ] Executive Overview accepted
[ ] AI Monitoring Summary accepted or blocker documented
[ ] Integration health reviewed for all four sources
[ ] No dashboard JSON contains credentials
[ ] Source-controlled dashboard JSON files validated
[ ] Custom dashboard backups preserved where applicable
[ ] PostgreSQL backup procedure understood
[ ] Restore rehearsal status recorded
[ ] HTTPS deployment status recorded
[ ] Direct backend exposure checked after final cutover
[ ] Known issues documented
[ ] Rollback owner identified
[ ] Operations owner identified
```

The handover is not complete if a FAIL item is simply ignored. It must either be corrected and retested or recorded as an accepted release limitation by the responsible owner.

## Stop conditions

**Stop here** and do not continue with live changes when any of these applies:

- release commit is unknown;
- Grafana/FastAPI configuration would need editing without explicit approval;
- a required plugin is missing and installation has not been approved;
- service restart/reload is required but not approved;
- dashboard import would overwrite an unbacked customized dashboard;
- datasource authentication cannot be verified;
- a source API is failing and the dashboard would merely hide that failure;
- TLS verification would need to be disabled;
- a certificate/private key would need to be copied into Git;
- the running FastAPI routes do not match the release candidate;
- database migration state is inconsistent;
- the operator cannot identify a safe rollback path.

When a stop condition is hit, record the symptom, the last successful check, and the evidence. Diagnose the dependency before continuing.

## Acceptance record template

Use this at the end of the handover:

```text
Release commit: ______________________________________
Grafana version: _____________________________________
Acceptance date/time: ________________________________
Operator: ____________________________________________
Reviewer: ____________________________________________

Wazuh Security:                 PASS / FAIL
Zabbix Infrastructure:         PASS / FAIL
Snipe-IT Asset Management:     PASS / FAIL
Freshservice Service Management: PASS / FAIL
Executive Overview:            PASS / FAIL
AI Monitoring Summary:         PASS / FAIL / NOT READY

Integration health reviewed:   YES / NO
Datasource verified:           YES / NO
Plugins verified:              YES / NO
Dashboard backups recorded:    YES / NO / N/A
PostgreSQL backup status:       _______________________
Restore rehearsal status:      _______________________
HTTPS deployment status:       _______________________
Known blockers:                _______________________
Rollback owner:                _______________________
Operations owner:              _______________________

Final disposition: ACCEPTED / ACCEPTED WITH LIMITATIONS / REJECTED
```

Do not mark the release accepted until every failure has an explicit disposition.