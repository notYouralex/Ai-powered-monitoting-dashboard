# Unified Monitoring Web Application Implementation Plan

## 1. Purpose

This document is the implementation plan for converting the existing AI-Powered Monitoring Dashboard project into a unified internal web application while preserving the current FastAPI business logic, normalized source contracts, authentication model, PostgreSQL persistence, local AI runtime, and Grafana dashboards during migration.

The target outcome is one authenticated internal web application where users can view the Executive, Wazuh, Zabbix, Snipe-IT, and Freshservice dashboards and use the AI investigation interface without opening Grafana for normal day-to-day use.

This plan is intentionally incremental. Grafana remains available until each replacement web dashboard has been validated against its existing canonical FastAPI data and accepted by the project owners.

This document supplements `AGENTS.md`, `docs/development/collaboration-rules.md`, and `docs/development/remaining-work-coordination.md`. If any rule conflicts, the stricter ownership, security, permission, or validation rule takes precedence.

---

## 2. Current Verified Baseline

At the time this plan was created, the repository already contains the core backend required for the web application.

Verified existing components include:

- FastAPI application in `app/main.py`.
- Local session-based authentication under `/api/auth/*`.
- Server-side opaque sessions stored securely with browser cookies.
- Dashboard access that accepts either an authenticated browser session or the read-only Grafana service token.
- PostgreSQL-backed application persistence.
- Wazuh dashboard API.
- Zabbix dashboard API.
- Snipe-IT dashboard API.
- Freshservice dashboard API.
- Executive dashboard API.
- Cross-source integration-health API.
- Local AI summary endpoints.
- Authenticated AI investigation endpoint.
- Existing same-origin AI web interface under `/ai`.
- Existing local HTML, CSS, and JavaScript assets under `app/web/static/`.
- Security headers on the current AI web page, including a self-only Content Security Policy.
- Existing tests verifying that the AI web page does not use external resources, browser storage, direct cookie access, or unsafe `innerHTML` rendering.
- Existing Grafana dashboards that remain the current reference presentation during migration.

Current canonical dashboard endpoints:

```text
GET /api/dashboard/executive
GET /api/dashboard/wazuh
GET /api/dashboard/zabbix
GET /api/dashboard/snipe-it
GET /api/dashboard/snipe-it/recent-activity
GET /api/dashboard/snipe-it/warranty-expiry
GET /api/dashboard/freshservice
GET /api/integrations/health
```

Current AI endpoints relevant to the web application:

```text
POST /api/ai/query
GET  /api/ai/insights/dashboard
GET  /api/ai/insights/executive
GET  /api/ai/insights/wazuh
GET  /api/ai/insights/zabbix
GET  /api/ai/insights/snipe-it
GET  /api/ai/insights/freshservice
```

Current authentication endpoints:

```text
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
```

The web application must reuse these contracts wherever practical instead of creating duplicate business logic.

---

## 3. Target User Experience

Users should open one internal HTTPS address, authenticate once, and navigate between all monitoring views.

Target navigation:

```text
AI-Powered Monitoring
|
+-- Executive
+-- Wazuh
+-- Zabbix
+-- Snipe-IT
+-- Freshservice
+-- AI Investigation
+-- Account / Sign out
```

Target application behavior:

1. User opens the internal monitoring URL.
2. If no valid session exists, the application displays the login view.
3. After successful login, the user is taken to the Executive dashboard.
4. Navigation occurs inside the same application shell.
5. Each dashboard retrieves canonical normalized data from FastAPI.
6. Source health and freshness are visible on each relevant page.
7. A failure in one source does not make unrelated dashboards unusable.
8. The AI interface uses the existing local AI backend and can be reached from the same navigation shell.
9. Dashboard-specific AI actions may prefill investigation questions, but the AI must remain read-only and explanatory.
10. Grafana remains accessible separately during migration and validation.

---

## 4. Architecture Decision

### 4.1 Selected approach

Extend the existing FastAPI-served same-origin web frontend into the full application.

Do not create a second backend service.

Do not move canonical dashboard calculations into JavaScript.

Do not replace existing source integration services merely to support the new frontend.

Initial target architecture:

```text
Browser
  |
  | HTTPS / same origin
  v
FastAPI
  |
  +-- Web shell and static assets
  +-- Authentication API
  +-- Executive API
  +-- Source dashboard APIs
  +-- Integration-health API
  +-- AI API
  |
  +-------------------+-------------------+-------------------+
  |                   |                   |                   |
Wazuh               Zabbix             Snipe-IT         Freshservice
  |                   |                   |                   |
  +-------------------+---------+---------+-------------------+
                                |
                           PostgreSQL
                                |
                           Local Ollama AI

Grafana remains a parallel presentation client during migration.
```

### 4.2 Frontend technology baseline

Use the existing project pattern first:

- server-served HTML;
- plain JavaScript modules or bounded JavaScript files;
- local CSS;
- same-origin `fetch`;
- native browser APIs;
- native HTML/SVG for tables, stat cards, simple charts, and topology where practical.

Do not introduce React, Vue, Angular, Node build tooling, a CDN, or a new package manager by default.

A third-party local visualization library may be considered later only if a specific dashboard requirement cannot be implemented maintainably with native HTML/SVG. Adding such a dependency requires a separate inspection, security/license review, and explicit permission because it changes the dependency/deployment footprint.

### 4.3 Why this approach is preferred

- Reuses the existing backend and normalized contracts.
- Reuses the existing authentication/session model.
- Keeps monitoring data inside the company network.
- Avoids duplicated business logic.
- Avoids a second frontend build pipeline initially.
- Preserves same-origin cookie security.
- Allows incremental migration from Grafana.
- Reduces operational complexity.
- Supports direct dashboard-to-AI workflows.

---

## 5. Non-Negotiable Design Rules

The following rules apply throughout implementation.

### 5.1 Backend owns metric meaning

The web frontend displays canonical FastAPI data.

It must not independently redefine:

- ticket status meanings;
- SLA compliance;
- overdue logic;
- source freshness;
- source health;
- Wazuh severity;
- Zabbix availability/problem definitions;
- Snipe-IT asset state;
- Executive health;
- AI evidence selection.

If a metric is wrong, fix its canonical backend contract or source-owned service, not only the frontend.

### 5.2 Source integrations remain read-only

The web application must not add:

- Wazuh active response;
- Zabbix configuration writes;
- Snipe-IT updates;
- Freshservice ticket writes;
- service restarts;
- shell/remote commands;
- firewall changes;
- automated remediation.

Any future write/remediation feature requires separate architecture approval and explicit permission.

### 5.3 No cloud fallback

Monitoring data, ticket data, asset data, security evidence, and AI prompts/evidence must not leave the company network.

### 5.4 Same-origin authenticated browser access

Dashboard requests from the web frontend use the existing session cookie through same-origin requests.

The frontend must not:

- read session cookies directly;
- store credentials in `localStorage`;
- store credentials in `sessionStorage`;
- place Grafana service tokens in JavaScript;
- expose source-system tokens to the browser.

### 5.5 Degraded operation

A stale, unavailable, failed, or not-configured source must be represented clearly but must not unnecessarily break unrelated views.

### 5.6 Grafana remains until validated

A Grafana dashboard is not retired merely because a web equivalent exists.

Retirement requires explicit acceptance after parity and runtime validation.

---

## 6. Proposed Web Route Structure

The implementation should converge on these routes:

```text
/                         -> redirect or serve application shell
/app                      -> Executive default view
/app/executive            -> Executive dashboard
/app/wazuh                -> Wazuh dashboard
/app/zabbix               -> Zabbix dashboard
/app/snipe-it             -> Snipe-IT dashboard
/app/freshservice         -> Freshservice dashboard
/app/ai                   -> AI Investigation
/app/assets/app.css       -> application stylesheet
/app/assets/app.js        -> application bootstrap/navigation
/app/assets/*.js          -> bounded local page/components modules if introduced
```

Backward compatibility during migration:

```text
/ai                       -> keep functional, or redirect to /app/ai only after compatibility tests pass
/ai/assets/*              -> keep until /ai migration is complete
```

Do not remove the old `/ai` entry point in the same change that introduces the new application shell unless tests and users have already migrated.

---

## 7. Proposed Frontend File Structure

Preferred end-state without introducing a build system:

```text
app/web/
├── __init__.py
├── router.py
└── static/
    ├── index.html
    ├── app.css
    ├── app.js
    ├── api.js
    ├── auth.js
    ├── navigation.js
    ├── ui.js
    ├── charts.js
    ├── pages/
    │   ├── executive.js
    │   ├── wazuh.js
    │   ├── zabbix.js
    │   ├── snipe-it.js
    │   ├── freshservice.js
    │   └── ai.js
    └── components/
        ├── status.js
        ├── tables.js
        ├── cards.js
        └── loading.js
```

This structure is a target, not permission for a large refactor. Create files only when the phase being implemented requires them.

The first implementation should preserve the current working AI behavior while extracting shared functionality incrementally.

---

## 8. Shared Frontend Conventions

### 8.1 API helper

Create one same-origin request helper that:

- uses `credentials: "same-origin"`;
- sets JSON content type only when needed;
- handles JSON error bodies safely;
- treats `401` as an expired/invalid session;
- never logs secrets or raw credentials;
- supports request cancellation where useful;
- exposes controlled user-facing errors.

### 8.2 DOM safety

Continue the existing safe rendering pattern:

- use `textContent` for source-derived text;
- avoid `innerHTML` for monitoring, ticket, asset, AI, or source values;
- create elements using DOM APIs;
- do not execute source-provided content;
- do not inject unsanitized HTML from AI output.

### 8.3 Loading states

Every data panel must support:

- initial loading;
- successful data;
- empty data;
- stale/degraded data where provided;
- API error;
- authentication expiration.

A page-level failure should not erase already-rendered valid data unless the contract requires it.

### 8.4 Formatting

Centralize common display formatting for:

- timestamps;
- durations;
- percentages;
- counts;
- severity labels;
- source names;
- freshness states;
- health states.

Display formatting must not change canonical metric meaning.

### 8.5 Accessibility

Minimum requirements:

- semantic headings;
- keyboard-accessible navigation;
- visible focus styles;
- buttons for actions rather than clickable generic elements;
- table headers for tabular data;
- text labels in addition to color;
- `aria-live` only for meaningful dynamic status;
- chart/table fallback or accessible labels for critical values.

### 8.6 Responsive behavior

The application should be usable at common desktop resolutions and remain navigable on tablet/smaller screens.

Desktop monitoring usability takes priority over phone-density optimization, but no page should become unusable because of horizontal layout assumptions.

---

## 9. Security Requirements

Each phase must preserve or improve the current web security baseline.

Required controls:

- same-origin assets only;
- no CDN dependencies by default;
- Content Security Policy remains restrictive;
- `Cache-Control: no-store` for authenticated application HTML;
- `X-Content-Type-Options: nosniff`;
- appropriate referrer policy;
- frame embedding denied unless architecture explicitly changes;
- HttpOnly session cookies remain server managed;
- secure cookies enabled in production HTTPS deployment;
- SameSite remains appropriately restrictive;
- no secrets in static assets;
- no API tokens in query strings;
- no monitoring credentials sent to the browser;
- no raw authorization headers logged;
- AI output rendered as untrusted text;
- source warnings rendered as untrusted text;
- browser requests bounded to approved application endpoints.

Before public or broader-network exposure, stop. This project is intended for internal company-network use only.

---

## 10. Time Range Behavior

Where the backend already accepts `from` and `to`, the frontend must send timezone-aware ISO timestamps.

Current relevant limits include a maximum 30-day backend range for Executive, Wazuh, and AI requests.

Frontend rules:

1. Do not bypass backend range validation.
2. Use browser-local display formatting but send timezone-aware timestamps.
3. Provide only ranges supported by the backend contract.
4. When a dashboard has a backend-defined period such as a six-month SLA trend, do not recreate that business calculation in JavaScript.
5. If the UI offers a range that the API does not support, the backend contract must be changed deliberately first.

---

## 11. Phased Implementation

Each phase is a separate logical implementation task unless explicitly combined by the project coordinator.

Every phase follows:

**Inspect -> Understand -> Define interface -> Write/update tests -> Get permission if required -> Implement -> Validate -> Review diff -> Report**

### Phase 0 - Baseline Freeze and Acceptance Inventory

#### Goal

Create a precise reference of what must be preserved before changing the current web experience.

#### Work

- Inspect current branch/worktree status.
- Record active dashboard/API behavior.
- Record current Grafana dashboard panels and their canonical API fields.
- Record the current AI page behavior.
- Identify which current uncommitted files belong to existing work so they are not overwritten.
- Build a migration parity checklist for each dashboard.
- Confirm current focused tests pass before web restructuring.

#### No implementation should happen if

- the current branch contains unresolved overlapping shared work;
- another active agent owns the same `app/web/**` write set;
- existing AI UI changes have not been reconciled;
- baseline tests already fail for unrelated reasons without being documented.

#### Exit criteria

- Reference panel inventory exists.
- Existing AI web tests are understood.
- Existing dirty changes are protected.
- The first phase write set is clear and non-overlapping.

---

### Phase 1 - Shared Application Shell and Authentication

#### Goal

Turn the current AI-only page into a reusable authenticated application shell without changing dashboard business logic.

#### Expected write zone

Primarily:

```text
app/web/**
tests/test_ai_web.py or new tests/test_web_*.py
```

`app/main.py` should only change if routing registration actually requires it. It is already registering `web_router`, so avoid unnecessary edits.

#### Work

- Add the main application shell.
- Add persistent top bar/sidebar navigation.
- Reuse `/api/auth/me`, `/api/auth/login`, and `/api/auth/logout`.
- Default authenticated view to Executive placeholder/skeleton.
- Add route handling for the target `/app/*` pages.
- Preserve `/ai` compatibility.
- Extract reusable same-origin request/auth helpers from the current AI JavaScript only as needed.
- Preserve all existing security headers.
- Preserve the current rule against browser credential storage.
- Add a generic page loading/error container.

#### Tests

Test at minimum:

- `/app` serves the local application shell.
- no external HTTP/HTTPS assets are present;
- application assets are same-origin;
- anonymous browser receives login view behavior;
- valid session exposes authenticated navigation;
- logout returns to login state;
- 401 from an application API returns the UI to login state;
- no `localStorage`, `sessionStorage`, direct `document.cookie`, or unsafe `innerHTML` use is introduced;
- `/ai` still works or intentionally redirects after compatibility is proven.

#### Exit criteria

- Login works.
- Navigation shell renders.
- AI remains reachable.
- No dashboard migration yet required.
- Existing auth tests still pass.

---

### Phase 2 - Executive Dashboard Web View

#### Goal

Implement the Executive dashboard as the first real web dashboard and establish reusable dashboard components.

#### Data sources

Primary:

```text
GET /api/dashboard/executive
GET /api/integrations/health
GET /api/ai/insights/executive   # optional AI panel, handled independently
```

#### Work

Implement the Executive web view using only normalized API data.

Expected content should match the accepted Executive dashboard design and current Grafana behavior, including as applicable:

- overall/source health overview;
- source freshness and last-success information;
- Executive counts/metrics already exposed by the API;
- Freshservice SLA trend representation;
- current source status summaries;
- optional Executive AI summary;
- explicit stale/degraded/unavailable state labels.

Do not copy Grafana transformations if they redefine canonical values.

#### AI behavior

The AI summary must not block the dashboard.

Recommended loading order:

1. Load dashboard data.
2. Render canonical metrics.
3. Load AI summary independently.
4. If AI is disabled/unavailable/slow, show a bounded AI status message while leaving the dashboard usable.

#### Tests

- correct API route is used;
- session credentials remain same-origin;
- healthy Executive response renders expected sections;
- degraded source is visibly identified;
- unavailable AI does not break the Executive dashboard;
- empty source data renders safely;
- source-derived text uses safe DOM rendering;
- time-range controls produce timezone-aware supported values if added.

#### Validation against Grafana

For the same backend snapshot/time range, compare:

- metric values;
- source health;
- freshness;
- table ordering/meaning where required;
- SLA trend values;
- AI summary source/period.

Visual layout does not need to be pixel-identical, but canonical values must agree.

#### Exit criteria

- Executive web dashboard accepted.
- Reusable cards/tables/health UI proven.
- Grafana Executive remains available.

---

### Phase 3 - Wazuh Web Dashboard

#### Ownership

Wazuh source integration remains Intern A-owned.

The shared web page may consume the existing Wazuh contract without modifying Wazuh source implementation.

If the frontend needs a missing canonical Wazuh field, stop and request a source-owner contract change rather than parsing raw Wazuh responses in the web layer.

#### Data sources

```text
GET /api/dashboard/wazuh
GET /api/ai/insights/wazuh      # optional
```

#### Work

Recreate the accepted Wazuh dashboard presentation from canonical fields, including the currently supported concepts such as:

- agent state;
- security alert totals;
- severity distribution;
- top affected agents;
- alert trend;
- recent alerts;
- source health/freshness;
- source-specific AI summary if enabled.

#### Required behavior

- support the existing maximum time range;
- do not expose Wazuh credentials;
- do not add active response/remediation buttons;
- stale/error state must not be disguised as healthy;
- AI remains optional and independent.

#### Exit criteria

- Web values match the Wazuh Grafana reference for the same range.
- Wazuh-focused tests pass.
- No Wazuh source-owned code changed unless separately approved and implemented by its owner.

---

### Phase 4 - Zabbix Web Dashboard

#### Ownership

Zabbix source integration remains Intern B-owned.

#### Data source

```text
GET /api/dashboard/zabbix
GET /api/ai/insights/zabbix     # optional
```

#### Work

Recreate the accepted infrastructure dashboard from the normalized cache, including supported concepts such as:

- host/interface availability;
- active problems and severity;
- CPU/resource pressure information;
- memory/resource pressure information;
- top affected hosts;
- trends;
- topology/network relationships exposed by the API;
- freshness and source warnings;
- source-specific AI summary if enabled.

#### Topology implementation

Prefer native SVG for topology visualization.

Topology rules:

- do not infer edges that the backend does not provide;
- use accessible labels;
- represent down/degraded state with text/icon/state in addition to color;
- animation, if used, must be subtle and must not hide state meaning;
- topology failure must not prevent other Zabbix panels from rendering.

#### Exit criteria

- Core Zabbix dashboard parity accepted.
- Topology is usable and does not redefine backend state.
- Grafana Zabbix dashboard remains available until acceptance.

---

### Phase 5 - Snipe-IT Web Dashboard

#### Ownership

Snipe-IT source integration remains Intern B-owned.

#### Data sources

```text
GET /api/dashboard/snipe-it
GET /api/dashboard/snipe-it/recent-activity
GET /api/dashboard/snipe-it/warranty-expiry
GET /api/ai/insights/snipe-it    # optional
```

#### Work

Recreate the accepted asset dashboard using normalized data, including supported concepts such as:

- total assets;
- assigned/unassigned assets;
- missing serial/tag indicators;
- warranty status/expiry;
- assets by category/type;
- assets by status;
- assets by location;
- recent activity;
- freshness and warnings;
- source-specific AI summary if enabled.

#### Required behavior

- preserve privacy constraints such as avoiding unnecessary assignee data;
- display stale/degraded state clearly;
- recent activity failure should not destroy already-valid cached dashboard content;
- no asset update/assignment actions.

#### Exit criteria

- Snipe-IT values match the accepted Grafana view/current API.
- Warranty and recent activity behavior are validated.

---

### Phase 6 - Freshservice Web Dashboard

#### Ownership

Freshservice source integration remains Intern A-owned.

#### Data source

```text
GET /api/dashboard/freshservice
GET /api/ai/insights/freshservice   # optional
```

#### Work

Recreate the accepted ticket/SLA dashboard using synchronized PostgreSQL data, including supported concepts such as:

- Open;
- Pending;
- Resolved;
- Closed;
- Due Today;
- Overdue;
- high-priority/escalated active tickets;
- status distribution;
- unresolved priority distribution;
- category distribution;
- resolution/SLA trend;
- recent ticket records;
- source freshness/health;
- source-specific AI summary if enabled.

#### SLA rule

The web application must display the backend's canonical SLA calculation.

Do not calculate a separate SLA result in JavaScript.

If the current requirement is a rolling six-month table, the backend-provided six-month data is the canonical source. The UI may format or order the returned rows but must not invent missing months or reinterpret ticket status rules.

#### Exit criteria

- Freshservice counts and SLA values match the accepted reference for the same data snapshot.
- No Freshservice ticket write behavior is introduced.

---

### Phase 7 - Unified AI Investigation Integration

#### Goal

Make the existing AI Investigation experience a first-class page inside the application shell and connect dashboard context to it safely.

#### Primary endpoint

```text
POST /api/ai/query
```

#### Work

- Move/reuse the existing AI chat UI inside `/app/ai`.
- Preserve the existing structured investigation rendering.
- Preserve source warnings, evidence, operational impact, contributing factors, confidence, and recommended investigation sections.
- Preserve the 1000-character question bound unless the backend contract changes deliberately.
- Preserve the backend 30-day maximum AI time range.
- Keep AI fully local.

#### Contextual dashboard actions

Pages may provide actions such as:

```text
Investigate with AI
```

The action may prefill a bounded question and optional source/device context in the AI page.

Examples:

```text
Why is SERVER-01 down?
Why is Snipe-IT currently degraded?
What is driving the current overdue Freshservice tickets?
What Wazuh issues need attention in the selected period?
```

Do not silently execute an AI request merely because a user opens a dashboard. The user should retain control over investigative queries unless a separately accepted UX design specifies otherwise.

#### Security

- AI response remains untrusted text.
- No HTML returned by the model is executed.
- No remediation tools are exposed.
- No source credentials are included in prompt/evidence.

#### Exit criteria

- Existing AI investigation regression tests pass.
- Dashboard-to-AI navigation works.
- AI failure never blocks non-AI dashboard access.

---

### Phase 8 - Cross-Dashboard UX, Refresh, and Performance

#### Goal

Standardize behavior after all main pages exist.

#### Work

- consistent page headers;
- consistent health/freshness chips;
- consistent loading states;
- consistent table behavior;
- consistent empty/error states;
- manual refresh button;
- optional bounded automatic refresh based on source/API characteristics;
- request cancellation when users navigate away;
- prevent duplicate in-flight requests;
- preserve last valid rendered data while a refresh is pending where appropriate;
- visible last-updated time;
- optional user-selected display density only if needed.

#### Refresh rules

Do not set a universal aggressive refresh interval.

Respect source characteristics:

- live/direct Wazuh request cost;
- Zabbix cached refresh cadence;
- Snipe-IT synchronization cadence;
- Freshservice synchronization cadence;
- AI generation/cache latency.

The frontend refresh interval must not pretend cached/synchronized data is more current than it actually is.

#### Exit criteria

- navigation does not leak/duplicate requests;
- refresh behavior is source-appropriate;
- stale status remains truthful;
- application remains responsive during AI requests.

---

### Phase 9 - Web Application Acceptance and Grafana Parity Review

#### Goal

Validate that the web application is ready to become the primary user interface.

#### Required parity matrix

For each dashboard compare the web app and Grafana against the same backend data/time range.

| Dashboard | Canonical values | Health/freshness | Trends | Tables | AI | Accepted |
|---|---|---|---|---|---|---|
| Executive | Required | Required | Required | Required | Optional | No initially |
| Wazuh | Required | Required | Required | Required | Optional | No initially |
| Zabbix | Required | Required | Required | Required | Optional | No initially |
| Snipe-IT | Required | Required | As applicable | Required | Optional | No initially |
| Freshservice | Required | Required | Required | Required | Optional | No initially |

#### Acceptance checks

- canonical values agree;
- degraded/stale states agree with API truth;
- no source has been made writable;
- authentication works across every page;
- logout invalidates the session;
- AI disabled/unavailable behavior is graceful;
- browser console has no material errors;
- network requests remain same-origin;
- no secret is present in frontend responses/assets;
- page reload on each supported `/app/*` route works;
- keyboard navigation is usable;
- common desktop viewport is usable;
- source failure does not incorrectly break unrelated views.

#### Exit criteria

The user/project coordinator explicitly accepts the web application as the normal user interface.

Grafana is still not removed in this phase.

---

### Phase 10 - Internal HTTPS and Deployment Hardening

#### Goal

Expose the application through the approved internal HTTPS deployment model.

#### Repository work may include

- reverse-proxy templates;
- secure deployment documentation;
- production cookie configuration guidance;
- health-check documentation;
- internal hostname assumptions represented as placeholders only.

#### Separate explicit permission required for live changes

- installing reverse-proxy packages;
- modifying system services;
- restarting/reloading services;
- firewall changes;
- DNS changes;
- TLS certificate installation;
- changing ports/listeners;
- production Compose/service changes;
- production database migration.

#### Security acceptance

- HTTPS active;
- secure cookie enabled;
- HTTP behavior intentionally redirected/rejected according to deployment design;
- private key material not committed;
- source/API services not unnecessarily exposed externally;
- only the required internal entry point is accessible.

---

### Phase 11 - Grafana Transition Decision

#### Goal

Decide Grafana's final role only after web acceptance.

Possible accepted end states:

1. **Grafana retained for administrators/advanced troubleshooting** - recommended default.
2. Grafana retained as a fallback/reference dashboard system.
3. Grafana retired later after a separate approval and operational review.

Do not delete Grafana dashboard definitions, provisioning files, or a live Grafana deployment as part of normal web migration without explicit permission.

If Grafana is retained, document which interface is authoritative for normal users and which use cases still belong in Grafana.

---

### Phase 12 - Documentation, Backup/Restore, and Final Handover

#### Required documentation updates

After implementation is stable, update as appropriate:

- `README.md` current implementation status;
- operator/deployment documentation;
- user login/navigation guide;
- dashboard behavior/reference guide;
- AI limitations and investigation behavior;
- Grafana fallback/administrator role;
- backup/restore procedure;
- troubleshooting guide.

#### Final handover must state

- final application URL/path model;
- required services;
- required environment settings by name only, never values;
- startup/rebuild procedure;
- validation procedure;
- backup/restore procedure;
- source sync behavior;
- AI runtime/model configuration locations;
- known limitations;
- Grafana's retained role;
- recovery steps if the web frontend fails.

---

## 12. Dashboard Migration Order

Recommended order:

```text
Phase 0  Baseline inventory
   |
Phase 1  Application shell + auth
   |
Phase 2  Executive
   |
Phase 3  Wazuh
   |
Phase 4  Zabbix
   |
Phase 5  Snipe-IT
   |
Phase 6  Freshservice
   |
Phase 7  Unified AI investigation
   |
Phase 8  Cross-dashboard UX/performance
   |
Phase 9  Acceptance/parity
   |
Phase 10 HTTPS/deployment hardening
   |
Phase 11 Grafana transition decision
   |
Phase 12 Documentation/handover
```

Executive is first because it exercises cross-source contracts, health, freshness, shared components, and AI summary behavior before the source-specific pages are migrated.

---

## 13. Ownership and Parallel-Work Rules

The web application introduces a new shared presentation surface. Treat `app/web/**` and shared web tests as shared architecture unless ownership is explicitly reassigned.

### Source ownership remains unchanged

| Source | Owner |
|---|---|
| Wazuh | Intern A |
| Freshservice | Intern A |
| Zabbix | Intern B |
| Snipe-IT | Intern B |

### Web work rule

One active implementer owns the `app/web/**` shared write lock for a given phase.

The other agent may review but should not concurrently edit the same files.

### If a web phase needs a source contract change

1. Stop before editing the source-owned integration.
2. Identify the missing canonical field/behavior.
3. Define the required contract change.
4. Have the owning intern implement the source change in a separate focused task/branch.
5. Validate and merge that source change.
6. Update the web branch from the merged baseline.
7. Continue the web page implementation.

### Parallel work allowed

Web UI work may run in parallel with unrelated source maintenance only if write sets are disjoint.

### Parallel work not allowed

Do not run two tasks concurrently if both modify:

- `app/web/**`;
- `app/main.py`;
- shared contracts required by the page;
- the same tests;
- deployment files;
- dependency/lock files.

---

## 14. Branch Strategy

Do not implement the entire migration in one branch.

Suggested branches:

```text
feature/web-app-shell
feature/web-executive-dashboard
feature/web-wazuh-dashboard
feature/web-zabbix-dashboard
feature/web-snipe-it-dashboard
feature/web-freshservice-dashboard
feature/web-ai-integration
feature/web-dashboard-ux
feature/web-acceptance
feature/internal-web-https
```

Each branch should be based on the latest accepted prerequisite branch after it has been merged.

Avoid long-lived branches that contain multiple dashboard migrations and unrelated backend changes.

---

## 15. Permission Gates

The user request to implement a particular repository phase can authorize the intended repository edits for that phase, but it does not authorize unrelated live/system changes.

Explicit permission is still required before:

- adding/upgrading/removing dependencies;
- installing system packages;
- applying live configuration changes;
- restarting/reloading/enabling services;
- changing Grafana live configuration;
- changing firewall/network/DNS/Tailscale;
- modifying systemd units;
- modifying production database data;
- applying production migrations;
- deleting files/data;
- removing Grafana;
- changing production dashboards;
- modifying source systems.

Inspection, source reads, safe searches, and non-destructive diagnostics may be performed without modification permission unless elevated privileges are required.

---

## 16. Test Strategy

### 16.1 Backend regression

Because the frontend depends on existing APIs, every implementation phase must preserve the backend suite.

Minimum after Python/backend changes:

```text
focused tests
full pytest suite
flake8
python compile checks
git diff --check
```

### 16.2 Web route tests

Test:

- application shell responses;
- security headers;
- asset content types;
- no open-directory asset exposure;
- old `/ai` compatibility during migration;
- route reload behavior.

### 16.3 Authentication tests

Test:

- anonymous state;
- valid session;
- expired session;
- logout;
- disabled user behavior via existing auth suite;
- no credential browser storage.

### 16.4 Page rendering contract tests

Where practical, verify each page JavaScript references only the approved API routes and contains expected safe rendering behavior.

Do not make fragile tests depend on every CSS class or exact visual spacing.

### 16.5 Runtime browser validation

When a local runtime is available, validate using a real browser session:

- login;
- page navigation;
- reload each route;
- network requests;
- console errors;
- loading/error states;
- AI query;
- logout;
- responsive viewport checks.

### 16.6 Dashboard parity validation

Use the same source snapshot/time range to compare web values with the reference Grafana dashboard.

A screenshot that looks similar is not sufficient. Compare actual values and states.

---

## 17. Definition of Done for Each Dashboard Page

A dashboard page is done only when all applicable items are true:

- uses canonical FastAPI endpoint(s);
- does not parse raw source API data;
- no source write behavior exists;
- valid authenticated session works;
- 401 behavior is handled;
- loading state exists;
- empty state exists;
- error state exists;
- degraded/stale state is truthful;
- critical data is accessible without relying only on color;
- source-derived text is rendered safely;
- relevant focused tests pass;
- full available test suite passes before merge;
- lint/syntax checks pass when applicable;
- runtime browser validation passes when available;
- values match the reference API/Grafana behavior;
- final diff contains only intended files;
- no secret is exposed;
- reviewer/owner approval is obtained where required.

If runtime validation cannot be performed, report exactly:

**The change has been prepared, but runtime validation has not been performed.**

---

## 18. Failure and Rollback Strategy

The migration must remain reversible.

### During development

- Keep each phase in a separate branch/commit scope.
- Preserve existing Grafana dashboards.
- Preserve old `/ai` behavior until the new AI page is accepted.
- Do not delete old assets in the same change that introduces replacements unless compatibility is proven.

### If a web dashboard fails validation

1. Do not alter canonical backend metrics merely to make the UI match an incorrect frontend assumption.
2. Determine whether the mismatch is frontend display logic, backend contract, stale source data, or Grafana presentation logic.
3. Keep Grafana as the active user view for that dashboard.
4. Fix the smallest responsible layer.
5. Re-run parity validation.

### If a deployment change fails

- restore the previous validated reverse-proxy/application configuration;
- preserve database state;
- do not delete synced monitoring data as a troubleshooting shortcut;
- keep Grafana available if it is still part of the accepted deployment.

---

## 19. Observability for the Web Application

The frontend should communicate state without exposing sensitive details.

Useful visible states:

- source health;
- source freshness;
- last successful observation/sync where available;
- AI availability;
- last dashboard refresh time;
- bounded user-facing error message.

Backend logs should continue using existing request IDs and safe controlled errors.

Do not add logging of:

- passwords;
- session tokens;
- authorization headers;
- API keys;
- source credentials;
- full sensitive ticket/asset payloads;
- private AI prompt context beyond what is already approved for safe application logging.

---

## 20. Performance Principles

- Render canonical dashboard data before optional AI content.
- Do not launch every dashboard API request on initial application login; load the active page first.
- Cancel or ignore stale requests when navigating.
- Avoid polling AI endpoints.
- Respect existing backend caches/sync intervals.
- Prefer tables for large detailed datasets rather than rendering thousands of DOM nodes in charts.
- Bound recent activity lists.
- Use pagination or backend-supported limits if detailed datasets grow beyond practical browser size.
- Avoid duplicating large API responses in browser storage.

---

## 21. AI-Specific Reliability Rules

AI is an enhancement, not a dependency for basic monitoring.

The application must remain useful when:

- `AI_ENABLED=false`;
- Ollama is unavailable;
- the configured model fails;
- AI request times out;
- AI summary cache is empty;
- AI produces a low-confidence result.

The UI must surface AI failure separately from monitoring-source failure.

Do not label an AI explanation as a confirmed root cause unless the backend result explicitly supports that confidence and evidence.

---

## 22. Data Privacy Rules

The web application should expose only the information required for monitoring and investigation.

- Avoid unnecessary user/assignee PII.
- Do not expose source credentials or internal authorization metadata.
- Do not include secret configuration in diagnostics shown to normal users.
- Preserve backend redaction/bounded evidence rules.
- Do not persist monitoring or AI response data in browser storage by default.

If a future requirement adds saved user preferences, define a server-side preference model or a specifically approved non-sensitive browser-storage policy rather than reusing browser storage for credentials or evidence.

---

## 23. Future Enhancements After Core Migration

These are explicitly not required for initial web migration:

- role-specific dashboards;
- saved per-user layouts;
- theme customization;
- export to PDF/CSV;
- saved investigation history;
- notification center;
- websocket/server-sent event live updates;
- mobile-first layout;
- advanced topology interaction;
- user-configurable dashboard widgets;
- write/remediation workflows;
- cloud AI.

Each should be evaluated separately after the core application is stable.

---

## 24. Implementation Checklist

Use this checklist for every phase.

### Before editing

- [ ] Confirm current branch/worktree.
- [ ] Confirm active shared-file owner/write lock.
- [ ] Read `AGENTS.md`.
- [ ] Read relevant collaboration/coordination rules.
- [ ] Inspect relevant current files.
- [ ] Inspect current tests.
- [ ] Identify the exact API contract consumed.
- [ ] State intended write set.
- [ ] Confirm no overlapping agent work.
- [ ] Confirm no dependency/system change is being assumed.

### During implementation

- [ ] Add/update focused tests.
- [ ] Keep source business rules in FastAPI.
- [ ] Use same-origin authenticated requests.
- [ ] Render untrusted values safely.
- [ ] Handle loading/empty/error/degraded states.
- [ ] Preserve old accepted behavior required for compatibility.
- [ ] Avoid unrelated refactors.

### Validation

- [ ] Focused tests pass.
- [ ] Full available test suite passes.
- [ ] Lint/syntax checks pass when applicable.
- [ ] `git diff --check` passes.
- [ ] Browser runtime check passes when available.
- [ ] Console has no material errors.
- [ ] Network requests are expected and same-origin.
- [ ] Dashboard values match canonical API/reference behavior.
- [ ] No secrets appear in the diff/assets/output.
- [ ] Final diff contains only intended files.

### Handoff

- [ ] Report files changed.
- [ ] Report contracts consumed/changed.
- [ ] Report validation commands/results.
- [ ] Report runtime validation status.
- [ ] Report known limitations.
- [ ] State whether Grafana remains the active fallback.
- [ ] State the exact next unblocked phase.

---

## 25. Final Project Acceptance Criteria

The unified web application is considered implementation-complete only when:

1. One internal authenticated web application provides Executive, Wazuh, Zabbix, Snipe-IT, Freshservice, and AI Investigation navigation.
2. Existing FastAPI normalized contracts remain the canonical source of metric meaning.
3. All source integrations remain read-only.
4. Browser authentication uses the existing secure session mechanism.
5. No source/system secret is exposed to frontend code.
6. AI remains fully local and optional.
7. AI failure does not break dashboards.
8. One source failure does not incorrectly break unrelated source views.
9. Web dashboard values have been validated against canonical API/Grafana reference behavior.
10. The required automated tests pass.
11. Runtime browser acceptance has been performed in the target environment.
12. Internal HTTPS deployment has been validated if included in release scope.
13. Backup/recovery and operations documentation are complete.
14. Grafana's retained or retired role is explicitly documented and approved.
15. The final diff/release contains no secrets or unrelated changes.

---

## 26. Recommended First Implementation Task

The first implementation task after this plan is accepted should be:

**Phase 0 + Phase 1: establish the migration baseline and build the shared authenticated `/app` shell while preserving the existing `/ai` interface.**

Do not begin by rewriting all dashboards at once.

The first change should prove these foundations:

- authenticated shell;
- same-origin API helper;
- navigation;
- secure static-asset routing;
- backward-compatible AI access;
- tests for the new web shell.

Once that is validated and merged, implement the Executive page as the first dashboard migration.

---

## 27. Plan Status

Status: **Implementation plan only. No web migration changes are authorized by this document itself beyond creation of this plan.**

The implementation must proceed phase by phase with repository inspection, ownership coordination, required permissions, focused validation, and final diff review for each task.
