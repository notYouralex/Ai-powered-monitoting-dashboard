# Web application acceptance and Grafana parity

This document records the Phase 9 repository-side acceptance review for the unified `/app/*` web application. It follows the acceptance outcomes used by the existing backend acceptance runbook:

- **PASS** — repository evidence or an executed check demonstrates the expected behavior.
- **PASS WITH CONDITION** — the expected behavior is present but depends on a documented condition.
- **FAIL** — the implementation is missing, inconsistent, insecure, or contradicted by evidence.
- **NOT RUN** — the check requires a running target environment, browser, or unavailable test tooling.

Do not mark a runtime or value-parity check PASS from source inspection alone.

## Scope

The accepted Grafana dashboards remain the comparison reference during Phase 9:

- `grafana/dashboards/executive.json`
- `grafana/dashboards/wazuh.json`
- `grafana/dashboards/zabbix-infrastructure.json`
- `grafana/dashboards/snipe-it.json`
- `grafana/dashboards/freshservice.json`

The unified web application routes are:

- `/app` and `/app/executive`
- `/app/wazuh`
- `/app/zabbix`
- `/app/snipe-it`
- `/app/freshservice`
- `/app/ai`

The legacy `/ai` page remains available during this phase. Grafana is not removed in Phase 9.

## Repository parity matrix

This matrix records contract and presentation coverage visible in the repository. It does **not** claim that live values have already been compared side by side in the target environment.

| Dashboard | Canonical API parity | Health/freshness | Trends/distributions | Tables | AI entry point | Repository result | Live value parity |
|---|---|---|---|---|---|---|---|
| Executive | PASS | PASS | PASS | PASS | PASS | PASS | NOT RUN |
| Wazuh | PASS | PASS | PASS | PASS | PASS | PASS | NOT RUN |
| Zabbix | PASS | PASS | PASS | PASS | PASS | PASS | NOT RUN |
| Snipe-IT | PASS | PASS | PASS WITH CONDITION | PASS | PASS | PASS | NOT RUN |
| Freshservice | PASS | PASS | PASS | PASS | PASS | PASS | NOT RUN |

Snipe-IT is **PASS WITH CONDITION** for trends because the accepted Grafana dashboard does not define a time-series trend panel; the web application preserves the applicable category/status/company distributions plus recent activity and warranty tables instead of inventing a trend contract.

## Canonical API comparison

The accepted Grafana dashboards and unified web application use the same normalized APIs:

| Dashboard | Canonical endpoint behavior |
|---|---|
| Executive | `/api/dashboard/executive` with explicit timezone-aware `from` and `to` for selectable 24h, 7d, or 30d ranges |
| Wazuh | `/api/dashboard/wazuh` with explicit timezone-aware `from` and `to` for selectable 24h, 7d, or 30d ranges |
| Zabbix | `/api/dashboard/zabbix` |
| Snipe-IT | `/api/dashboard/snipe-it`, `/api/dashboard/snipe-it/recent-activity`, and `/api/dashboard/snipe-it/warranty-expiry` |
| Freshservice | `/api/dashboard/freshservice` |

The Phase 9 review found and corrected one repository parity gap: the accepted Executive Grafana dashboard passes `from`/`to`, while the web Executive view previously relied on the backend default range. The web view now exposes 24h/7d/30d controls and sends explicit timezone-aware bounds, matching the API's 30-day maximum.

## Accepted Grafana concept coverage

### Executive

The web view contains the accepted concepts: Overall Health, Security Alerts, Open Tickets, Overdue Tickets, SLA Compliance, Assets, High-Severity Issues by Domain, Tickets by Status, Source Health & Freshness, and Attention Required. Source health retains the accepted column order: Last Success, Source, Freshness, Status.

### Wazuh

The web view contains the accepted concepts: Total/Critical/High Alerts, Total/Critical/High Vulnerabilities, Alert Trend, MITRE Tactics, Top Alerts, Vulnerabilities by Severity, Top Affected Agents, Agent Status, and Recent Alerts. It also displays normalized source health, freshness, and warnings.

### Zabbix

The web view contains the accepted concepts: Hosts, Problems, Unreachable, Avg CPU Usage, Critical Problems, Live Host Topology, System Information, CPU Load, Memory Usage, warnings, Network Latency, and Network Bandwidth. The native SVG topology uses only backend-provided nodes and edges; it does not infer missing links.

### Snipe-IT

The web view contains the accepted concepts: Total Assets, Deployed, Available, Maintenance, Retired, Assets by Type / Category, Assets by Status, Assets by Company, Recent Activity, and Upcoming Warranty Expiry. The web view also exposes normalized assigned/unassigned, data-quality, location, and warranty summary fields supported by the canonical API. Recent activity follows the accepted Grafana fields and does not add the activity location field.

### Freshservice

The web view contains the accepted concepts: Open, Pending, Resolved, Closed, Due Today, Overdue, Resolution SLA Compliance, unresolved priority/status distributions, all-ticket status distribution, Resolution Trend, Recent Tickets, and Historical Resolution SLA Compliance. The historical SLA table renders the canonical backend-provided rolling six-month rows rather than recalculating SLA in the browser.

## Acceptance checks

| Check | Phase 9 status | Evidence / required follow-up |
|---|---|---|
| Canonical endpoint and field contracts agree with accepted Grafana definitions | PASS | Static dashboard/API/web contract review and source-level checks |
| Executive and Wazuh can use the same explicit comparison time range as Grafana | PASS | 24h/7d/30d controls with timezone-aware `from`/`to`; API maximum is 30 days |
| Degraded/stale states are represented from API truth | PASS | Web renderers consume normalized `health`, `is_stale`, warnings, and observed/last-success timestamps |
| Source integrations remain read-only | PASS | Phase 9 made no source integration changes or write actions |
| Authentication boundary exists on every `/app/*` route | PASS WITH CONDITION | Secure session implementation and test coverage exist; target-browser login traversal is still NOT RUN |
| Logout invalidates the session | PASS WITH CONDITION | Backend auth test coverage exists; Phase 9 target-browser verification is still NOT RUN |
| AI disabled/unavailable behavior is graceful | PASS WITH CONDITION | Web request handling preserves dashboard independence; target runtime with AI disabled/unavailable is NOT RUN |
| Network requests remain same-origin | PASS | Shared request helper uses `credentials: "same-origin"`; frontend uses relative API routes |
| Frontend assets contain no source credentials or secrets | PASS | Static scan found no known source credential/config identifiers in the unified frontend assets |
| Page reload works on each supported `/app/*` route | NOT RUN | Requires running target application/browser acceptance |
| Browser console has no material errors | NOT RUN | Requires target browser developer-console inspection |
| Keyboard navigation is usable | NOT RUN | Requires interactive browser acceptance |
| Common desktop viewport is usable | NOT RUN | Requires interactive browser acceptance |
| One source failure does not incorrectly break unrelated views | PASS WITH CONDITION | Isolation exists in service/web design and tests; target runtime failure exercise remains NOT RUN |
| Web and Grafana display matching live values for the same data/time range | NOT RUN | Requires simultaneous target-environment comparison |
| Required automated tests pass | NOT RUN | The current MCP host does not provide `pytest`; do not install it as part of acceptance without separate approval |

## Target-environment parity procedure

For each dashboard, use the same user/session and compare the web application with the accepted Grafana dashboard against the same backend state. For Executive and Wazuh, select the same time window. Record the canonical API response when a mismatch needs investigation; do not alter source data to make values match.

1. Sign in to the unified web application and verify every navigation route loads after a direct page reload.
2. Open the equivalent accepted Grafana dashboard.
3. For Executive and Wazuh, set matching time ranges. Use 24h first, then exercise 7d and 30d.
4. Compare headline values, distributions/trends, tables, freshness, health, and warnings against the canonical API response.
5. Exercise manual Refresh while valid data is already visible and confirm a failed refresh does not erase the last valid observation.
6. Verify Snipe-IT recent-activity or warranty failure does not erase the valid cached main dashboard.
7. Verify AI unavailable/disabled behavior does not break dashboard navigation or rendering.
8. Check browser developer tools for material console errors and unexpected cross-origin requests.
9. Traverse the navigation, range controls, Refresh buttons, AI composer, sign-in, and logout using the keyboard.
10. Verify the normal company desktop viewport is usable without overlapping controls or inaccessible content.
11. Log out and confirm authenticated API access is no longer available with that session.

## Runtime acceptance record

Complete this in the target environment without secrets:

```text
Date/time:
Release Git commit:
Tester/reviewer:
Target hostname/environment:

Authentication/login: PASS / FAIL / NOT RUN
Logout/session invalidation: PASS / FAIL / NOT RUN
Direct reload of all /app/* routes: PASS / FAIL / NOT RUN
Same-origin network requests: PASS / FAIL / NOT RUN
Browser console: PASS / FAIL / NOT RUN
Keyboard navigation: PASS / FAIL / NOT RUN
Desktop viewport: PASS / FAIL / NOT RUN
AI unavailable/disabled behavior: PASS / PASS WITH CONDITION / FAIL / NOT RUN
Source-failure isolation: PASS / PASS WITH CONDITION / FAIL / NOT RUN

Executive live Grafana/API parity: PASS / FAIL / NOT RUN
Wazuh live Grafana/API parity: PASS / FAIL / NOT RUN
Zabbix live Grafana/API parity: PASS / FAIL / NOT RUN
Snipe-IT live Grafana/API parity: PASS / PASS WITH CONDITION / FAIL / NOT RUN
Freshservice live Grafana/API parity: PASS / FAIL / NOT RUN

Required automated tests: PASS / FAIL / NOT RUN
Reviewer notes/approved conditions:
Final web-app acceptance: ACCEPTED / NOT ACCEPTED
```

## Phase 9 repository outcome

The repository-side parity review can be completed before deployment, but the web application must **not** be declared the accepted normal user interface until the NOT RUN runtime checks above are executed with evidence and the project coordinator explicitly accepts the result.

Phase 9 does not remove Grafana and does not authorize Phase 10 deployment or HTTPS changes.
