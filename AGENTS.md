# Repository Development Rules

## Ownership

- Intern A owns Wazuh and Freshservice implementation, tests, and source dashboards.
- Intern B owns Zabbix and Snipe-IT implementation, tests, and source dashboards.
- The Executive dashboard, shared contracts, core/database architecture, correlation, integration health, migrations, deployment files, and cross-source AI models are shared ownership.
- Do not modify another intern's owned integration directly. Agree on a shared contract change when cross-domain behavior is needed.

## Required Workflow

Inspect -> Understand -> Define interface -> Write tests -> Implement -> Validate -> Review diff -> Merge.

Do not develop features directly on `main`. Keep each branch limited to one logical feature or fix.

## Shared Changes

Only one developer should actively implement a given shared-file change at a time. Agree on the interface first, add/update shared tests, have the other intern review, merge the shared change, then update dependent feature branches.

## Executive Dashboard Boundary

The Executive dashboard is an aggregator. It consumes normalized shared source summaries and must not parse or depend on raw source API responses.

Each source owner is responsible for producing that source's normalized Executive summary. A failed or stale source must not break unrelated source summaries.

## Security

All source integrations are read-only. Do not add Wazuh active response, Zabbix configuration writes, Snipe-IT updates, Freshservice ticket writes, remote commands, service restarts, or firewall changes without explicit architecture approval.

Never commit or log passwords, API keys, tokens, authorization headers, private keys, production connection strings, or unnecessary sensitive source data. No monitoring, asset, or ticket data may leave the company network.

## Configuration and Migrations

Use source-prefixed integration configuration: `WAZUH_`, `FRESHSERVICE_`, `ZABBIX_`, and `SNIPE_IT_`.

Migrations are shared infrastructure. Never edit an already merged migration for a new feature. Inspect the current Alembic head and coordinate before creating a shared migration.

## CODEOWNERS

Do not guess GitHub identities. Create or update `.github/CODEOWNERS` only after verified GitHub review handles for both interns are available.

## Validation

Before merge, run focused tests and the full available test suite, validate syntax/configuration affected by the change, review the final diff, and confirm no secrets or unrelated changes are present.

See `docs/development/collaboration-rules.md` for the complete operating procedure.
