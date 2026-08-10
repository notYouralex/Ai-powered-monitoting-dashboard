# Two-Intern Collaboration Controls — Design

**Date:** 2026-08-10
**Status:** Approved
**Applies to:** AI-Powered Monitoring Dashboard repository

## 1. Goal

Establish repository-level collaboration rules that let two interns develop separate source integrations in parallel without silently changing each other's implementations or breaking the shared Executive dashboard.

The development split is:

- **Intern A:** Wazuh and Freshservice ITSM
- **Intern B:** Zabbix and Snipe-IT
- **Shared:** Executive dashboard and cross-source platform contracts

The existing approved security boundary remains unchanged: source integrations are read-only, internal-network only, and no monitoring, asset, or ticket data may leave the company network.

## 2. Design Principles

1. **Domain ownership:** each intern owns the implementation, tests, and source dashboard for their assigned integrations.
2. **Contract-first shared code:** the Executive dashboard consumes stable normalized contracts rather than source-specific API responses.
3. **Explicit shared ownership:** files that affect both interns are treated as shared and require coordination before modification.
4. **Small feature branches:** no integration development directly on `main`; one logical feature or fix per branch.
5. **Backward-compatible contracts:** shared schema changes are additive when practical and require affected tests before merge.
6. **No invented ownership identities:** GitHub CODEOWNERS entries are activated only when the actual GitHub usernames or team handles for both interns are known.

## 3. Ownership Boundaries

### Intern A ownership

Primary implementation paths:

```text
app/integrations/wazuh/
app/integrations/freshservice/
tests/integrations/test_wazuh*
tests/integrations/test_freshservice*
grafana/dashboards/wazuh/
grafana/dashboards/freshservice/
```

Responsibilities include adapters, normalization, source-specific services/endpoints, source-specific tests, and source-specific dashboards.

### Intern B ownership

Primary implementation paths:

```text
app/integrations/zabbix/
app/integrations/snipe_it/
tests/integrations/test_zabbix*
tests/integrations/test_snipe_it*
grafana/dashboards/zabbix/
grafana/dashboards/snipe_it/
```

Responsibilities mirror Intern A for the assigned integrations.

### Shared ownership

The following are shared architectural surfaces:

```text
AGENTS.md
docs/development/
app/contracts/
app/core/
app/db/
app/main.py
app/dashboard/executive/
app/integrations/health/
app/normalization/
app/correlation/
grafana/dashboards/executive/
migrations/
compose.yaml
Dockerfile
.env.example
pyproject.toml
```

Only one developer should actively implement a given shared-file change at a time. The other developer reviews the change before integration into `main`.

## 4. Executive Dashboard Boundary

The Executive dashboard is an aggregator, not an integration adapter.

```text
Wazuh -----------\
Freshservice -----\
                  > normalized source summaries -> Executive service -> API -> Grafana
Zabbix -----------/
Snipe-IT --------/
```

Each integration owner produces a normalized Executive summary for their sources. The shared Executive layer combines those summaries without importing or interpreting raw source payloads.

Source-specific fields must stop at the integration boundary. A source adapter may change internally without forcing changes to the Executive dashboard as long as its shared contract remains compatible.

## 5. Initial Shared Contracts

Implementation will introduce a focused `app/contracts/` package. It will contain source-neutral Pydantic models only; source clients and network calls do not belong there.

### Integration source identifiers

Canonical identifiers:

```text
wazuh
zabbix
snipe_it
freshservice
```

### Integration health states

Canonical states remain those from the approved platform design:

```text
healthy
degraded
unavailable
not_configured
```

### Integration health summary

The initial shared health contract will represent:

```text
source
status
observed_at
last_success_at       optional
response_time_ms      optional
is_stale
warnings              list of safe human-readable strings
```

It must not contain credentials, authorization data, connection strings, or raw source responses.

### Executive source summary

The shared Executive boundary will define a small envelope containing:

```text
source
observed_at
is_stale
health
metrics
warnings
```

`metrics` is a bounded source-summary mapping intended for Executive KPIs only. Metric values are scalar (`int`, `float`, `str`, `bool`, or `null`); nested dictionaries/lists are rejected so this field cannot become a container for raw source payloads. Contract validation also requires the envelope source to match the embedded health-summary source. Source-specific detailed models remain inside each integration package.

The first implementation creates the contract types and validation tests only; it does not implement Wazuh, Freshservice, Zabbix, Snipe-IT, or Executive aggregation logic.

## 6. Repository Collaboration Files

### `AGENTS.md`

A repository-root `AGENTS.md` will encode the rules that humans and coding agents must follow:

- ownership boundaries
- inspect-before-edit behavior
- no direct changes to another intern's owned integration
- shared-contract change protocol
- branch/validation requirements
- security and read-only restrictions
- Executive dashboard aggregation boundary
- migration coordination rules

This file complements, rather than replaces, the approved architecture specification.

### `docs/development/collaboration-rules.md`

Human-readable operating procedure covering:

- ownership matrix
- branch naming
- commit conventions
- pull-request expectations
- conflict prevention
- migration coordination
- configuration naming
- testing responsibilities
- definition of done

### `.github/CODEOWNERS`

A real CODEOWNERS file must use verified GitHub usernames or organization-team handles. Repository Git author names and a remote repository owner are not sufficient evidence to identify both interns' review handles.

Therefore implementation will **not create invalid or guessed CODEOWNERS entries**. Instead:

1. add a documented ownership matrix immediately;
2. add `.github/CODEOWNERS` only after both real GitHub handles are available;
3. when activated, owned integration paths require the owning intern and shared paths require both owners where GitHub repository settings support that review policy.

This avoids a misleading CODEOWNERS file that appears enforced but is not.

## 7. Git Workflow

Once both interns are contributing, development work follows:

```text
main
  -> feature/wazuh-...
  -> feature/freshservice-...
  -> feature/zabbix-...
  -> feature/snipe-...
  -> feature/executive-...
  -> fix/<component>-...
```

Rules:

- do not develop features directly on `main`;
- start from an updated `main`;
- keep branches focused on one logical change;
- merge through review once collaboration begins;
- never force-push shared branches;
- do not bundle unrelated integrations in one feature branch.

Recommended commits use component scopes, for example:

```text
feat(wazuh): add agent status adapter
feat(freshservice): add ticket normalization
feat(zabbix): add host availability service
feat(snipe): add asset normalization
feat(executive): add integration health summary
fix(wazuh): handle pagination safely
test(freshservice): cover rate limiting
```

## 8. Shared-Change Protocol

When either intern needs a shared architectural change:

1. explain the required interface change;
2. agree on the contract before implementation;
3. assign one developer to implement the shared change;
4. add or update shared tests;
5. have the other developer review it;
6. merge the shared change first;
7. both feature branches update from the new `main`;
8. continue source-specific work.

This protocol applies especially to database models, Alembic migrations, shared contracts, Executive schemas, authentication, Compose, and cross-source AI evidence models.

## 9. Database Migration Coordination

Migrations are shared infrastructure.

- Never edit an already merged migration to add a new feature.
- Inspect the current Alembic head before creating a revision.
- Coordinate if both interns need migrations at the same time.
- Prefer a single linear migration history unless multiple heads are intentionally designed and tested.
- Validate upgrade behavior before merge.

## 10. Configuration Rules

Integration-specific environment variables use explicit prefixes:

```text
WAZUH_...
FRESHSERVICE_...
ZABBIX_...
SNIPE_IT_...
```

Do not introduce ambiguous shared names such as generic `API_URL`, `API_KEY`, `USERNAME`, or `PASSWORD` for source integrations.

Secrets remain excluded from Git; `.env.example` contains placeholders only.

## 11. Testing and Definition of Done

Each intern owns tests for their integrations. Minimum adapter coverage should include successful retrieval, empty responses, pagination where applicable, timeouts, authentication failure, unavailable source, malformed source data, rate limiting where applicable, normalization, and proof that no source-write operation is introduced.

Shared Executive tests cover healthy, degraded, unavailable, stale, and empty-source combinations without allowing one failed source to break unrelated summaries.

Before merge, a change must have:

- focused tests for changed behavior;
- the full available test suite passing;
- syntax/configuration validation where relevant;
- no exposed secrets;
- no source-write behavior;
- compatible shared contracts;
- safe errors/logging;
- migration and Compose validation when changed;
- a reviewed diff containing only intended files.

## 12. Implementation Scope for Collaboration Controls

The collaboration-controls implementation is intentionally small. It will:

1. add `AGENTS.md`;
2. add `docs/development/collaboration-rules.md`;
3. add `app/contracts/` with the initial source-neutral health and Executive-summary models;
4. add tests for those contracts;
5. document that CODEOWNERS activation is pending verified GitHub review handles for both interns.

It will not:

- implement any source adapter;
- create database migrations;
- change authentication;
- change Compose services;
- create Grafana dashboards;
- alter the approved integration/security boundaries;
- guess or fabricate the second intern's GitHub identity.

## 13. Success Criteria

The controls are successful when:

- both interns can identify owned and shared paths without ambiguity;
- coding agents receive the same ownership and safety instructions;
- Executive consumers depend on shared contracts rather than raw source formats;
- shared changes have a defined review/coordination workflow;
- contract tests pass independently of external systems;
- no source implementation or runtime behavior changes as part of this control work;
- CODEOWNERS is activated only with verified identities.
