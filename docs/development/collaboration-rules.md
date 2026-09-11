# Two-Intern Collaboration Rules

## Ownership Matrix

| Area | Intern A | Intern B | Shared |
|---|---|---|---|
| Wazuh integration/dashboard | Owner | - | - |
| Freshservice integration/dashboard | Owner | - | - |
| Zabbix integration/dashboard | - | Owner | - |
| Snipe-IT integration/dashboard | - | Owner | - |
| Executive dashboard | Contributor | Contributor | Owner |
| Shared contracts | Contributor | Contributor | Owner |
| Integration health/correlation | Contributor | Contributor | Owner |
| Database/migrations | Contributor | Contributor | Owner |
| Authentication/deployment | Contributor | Contributor | Owner |
| Cross-source AI orchestration | Contributor | Contributor | Owner until separately assigned |

Intern A owns `app/integrations/wazuh/`, `app/integrations/freshservice/`, their tests, and their source dashboards. Intern B owns the corresponding Zabbix and Snipe-IT paths. Shared paths include `app/contracts/`, `app/core/`, `app/db/`, `app/dashboard/executive/`, `app/integrations/health/`, `app/correlation/`, `app/ai/`, any future shared normalization package, `migrations/`, Executive/AI Grafana dashboards and provisioning, `compose.yaml`, `Dockerfile`, `.env.example`, and `pyproject.toml`.

## Integration Boundary

Source-specific API formats stop inside their owning integration packages. Executive/dashboard/AI code consumes normalized contracts only and must not parse raw source responses.

## Executive Dashboard

Intern A provides normalized Wazuh and Freshservice Executive summaries. Intern B provides normalized Zabbix and Snipe-IT Executive summaries. Both interns co-own aggregation, overall-health behavior, the Executive API, and Executive Grafana layout.

One failed, stale, empty, or unavailable source must not prevent unrelated source summaries from being returned.

## Branch and Commit Workflow

Do not develop features directly on `main`. Start from an updated `main` and use one focused branch per logical change, for example `feature/wazuh-agents`, `feature/freshservice-tickets`, `feature/zabbix-hosts`, `feature/snipe-assets`, `feature/executive-health`, or `fix/<component>-<issue>`.

Use component-scoped commits such as `feat(wazuh): ...`, `feat(freshservice): ...`, `feat(zabbix): ...`, `feat(snipe): ...`, `feat(executive): ...`, `fix(<component>): ...`, and `test(<component>): ...`.

Do not force-push shared branches or bundle unrelated integrations in one feature branch.

## Pull Request Review

Before review: update from `main`, resolve conflicts on the feature branch, run focused tests, run the full available suite, review the diff, verify no credentials are present, and confirm unrelated components were not modified.

Do not modify another intern's owned integration directly as the normal workflow. Request the needed behavior from the owning intern or agree on a shared contract change first. If both interns explicitly agree that an exceptional cross-domain edit is necessary, the owning intern must review it before merge. Shared architectural changes require review from both interns before merge.

## Shared-Change Protocol

1. Explain the required shared interface change.
2. Agree on the contract before implementation.
3. Assign one active implementer for the shared files.
4. Add or update shared tests.
5. Have the other intern review the change.
6. Merge the shared change first.
7. Both developers update dependent branches from the new `main`.
8. Continue source-specific work.

## Migration Coordination

Migrations are shared infrastructure. Never edit an already merged revision for a new feature. Inspect the current Alembic head before creating a revision and coordinate if both interns need schema changes. Prefer one linear migration history unless multiple heads are deliberately designed and tested.

## Configuration

Use source-specific prefixes: `WAZUH_`, `FRESHSERVICE_`, `ZABBIX_`, and `SNIPE_IT_`. Do not add ambiguous integration variables such as generic `API_URL`, `API_KEY`, `USERNAME`, or `PASSWORD`.

Secrets belong in ignored local configuration or the approved secret-management process. `.env.example` contains placeholders only.

## Security Boundary

All source access remains read-only. Do not implement Wazuh active response, Zabbix configuration writes, Snipe-IT updates, Freshservice ticket writes, remote commands, service restarts, firewall changes, cloud AI fallback, or public exposure without explicit architecture approval.

## Testing Responsibilities

Each integration owner tests successful retrieval, empty responses, pagination where applicable, timeouts, authentication failure, unavailable sources, malformed source data, rate limiting where applicable, normalization, and absence of source-write behavior.

Shared Executive tests cover healthy, degraded, unavailable, stale, and empty-source combinations and verify one source failure does not break unrelated summaries.

## CODEOWNERS Activation

Do not infer review handles from Git author names or repository ownership. Add `.github/CODEOWNERS` only after verified GitHub review handles for both interns are known. At that point, integration paths map to their owners and shared paths map to both reviewers, subject to repository branch-protection settings.

## Definition of Done

A change is ready to merge only when relevant tests exist and pass, the full available suite passes, affected syntax/configuration is validated, no secrets or source-write behavior were introduced, shared contracts remain compatible, errors/logging are safe, migrations/Compose are validated when changed, and the final diff contains only intended files.
