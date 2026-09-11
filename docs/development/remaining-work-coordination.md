# Implementation Coordination Plan and Current Status

## Purpose

This document records the project coordination model used by the two interns and their AI agents so that independent tasks can proceed without overlapping edits, conflicting migrations, competing shared-file changes, or accidental modification of another owner's integration.

It supplements `AGENTS.md` and `docs/development/collaboration-rules.md`. If this document conflicts with either of them, the stricter ownership, security, review, or validation rule takes precedence.

This file is a coordination reference. During normal implementation, AI agents should read it but should not edit it unless the user or designated project coordinator explicitly asks for an assignment change.

## Current Repository Status

The milestone sequence below was written before the shared backend, Grafana, AI, correlation, and deployment-preparation work was completed. It is retained to document ownership and the implementation order that was used, but it is no longer a list of unfinished repository features.

The current repository includes:

- the shared Executive aggregator/API under `app/dashboard/executive/` and `GET /api/dashboard/executive`;
- the project-maintained Executive Grafana dashboard at `grafana/dashboards/executive.json`;
- device correlation under `app/correlation/`, with worker ingestion from Wazuh, Zabbix, and Snipe-IT observations;
- cross-source integration-health aggregation under `app/integrations/health/` and `GET /api/integrations/health`;
- standardized inert Grafana provisioning/reference files for the host-installed Grafana deployment model;
- local Ollama-backed AI orchestration under `app/ai/`, including investigation, readiness, combined dashboard summary, and source-summary endpoints;
- the `AI Monitoring Summary` Grafana dashboard at `grafana/dashboards/ai-summary.json`;
- an internal HTTPS Nginx template plus the deployment runbook under `deploy/nginx/` and `docs/deployment/internal-https.md`;
- backend acceptance, PostgreSQL backup/restore, and Grafana operations/handover runbooks under `docs/deployment/`.

The remaining work is environment-specific deployment and runtime acceptance: deploy the approved release, supply protected source configuration, activate the approved HTTPS/reverse-proxy changes, validate the configured integrations and dashboards, rehearse database restore, and complete handover. The separate unified web-dashboard migration described in `docs/development/web-app-implementation-plan.md` is still planned; the current browser UI exposes `/ai`, not the proposed `/app/*` dashboard shell. Do not execute the historical milestones below merely because they remain documented; inspect the current repository first and create a new scoped task for any further change.

## Agent and Source Ownership

For this document:

- **Agent A / Intern A** owns Wazuh and Freshservice source implementation.
- **Agent B / Intern B** owns Zabbix and Snipe-IT source implementation.
- Shared architecture is not permanently owned by either agent. Each shared task has one temporary **primary implementer** and one **reviewer**.

Permanent source ownership remains:

| Area | Primary owner | Other agent |
|---|---|---|
| `app/integrations/wazuh/**` | Agent A | Read/review only |
| `tests/integrations/test_wazuh_*` | Agent A | Read/review only |
| `grafana/dashboards/wazuh.json` | Agent A | Read/review only |
| `app/integrations/freshservice/**` | Agent A | Read/review only |
| `tests/integrations/test_freshservice_*` | Agent A | Read/review only |
| `grafana/dashboards/freshservice.json` | Agent A | Read/review only |
| `app/integrations/zabbix/**` | Agent B | Read/review only |
| `tests/integrations/test_zabbix_*` | Agent B | Read/review only |
| `grafana/dashboards/zabbix-infrastructure.json` | Agent B | Read/review only |
| `app/integrations/snipe_it/**` | Agent B | Read/review only |
| `tests/integrations/test_snipe_it_*` | Agent B | Read/review only |
| `grafana/dashboards/snipe-it.json` | Agent B | Read/review only |

An agent must not modify the other agent's source-owned paths as part of a shared task. If a shared contract requires a source adapter change, the source owner performs that adapter change in a separate branch after the shared contract is agreed and merged.

## Shared Paths Require an Exclusive Write Lock

The following paths are shared. Only the primary implementer of the active shared task may modify them unless the user explicitly reassigns ownership:

- `app/contracts/**`
- `app/core/**`
- `app/db/**`
- `app/main.py`
- `app/worker.py`
- `app/integrations/router.py`
- `app/dashboard/executive/**`
- `app/integrations/health/**`
- `app/correlation/**`
- `app/ai/**` and other shared AI/orchestration paths
- `migrations/**`
- `compose.yaml`
- `Dockerfile`
- `.env.example`
- `pyproject.toml`
- `uv.lock`
- `grafana/provisioning/**`
- `grafana/dashboards/executive.json`
- `grafana/dashboards/ai-summary.json`
- shared tests that exercise cross-source behavior

The following coordination/project-policy files are coordinator-owned and should not be edited incidentally by either implementation agent:

- `AGENTS.md`
- `README.md`
- `docs/development/collaboration-rules.md`
- `docs/development/remaining-work-coordination.md`

If an implementation task requires changing one of these coordinator-owned files, the change must be explicitly included in that task's approved write set.

## Core Conflict-Prevention Rule

**One shared file, one active writer.**

Two AI agents may work at the same time only when their planned write sets are disjoint. Reading the same files is allowed. Editing the same file, the same migration chain, the same shared contract, or the same generated lock file at the same time is not allowed.

If both tasks require the same shared file:

1. Stop the second task before editing.
2. Finish and merge the first shared task.
3. Update the second branch from the new `main`.
4. Re-inspect the merged interface.
5. Continue the second task against the new baseline.

Do not solve this situation by letting both agents edit and resolving the conflict later.

## Original Milestones and Primary Assignment

The original roadmap was split as follows. These assignments describe the implementation sequence and ownership model; use the current-status section above to determine what is already present in the repository.

| Order | Milestone | Primary implementer | Reviewer | Default dependency |
|---|---|---|---|---|
| 1 | Shared Executive aggregator/API | Agent A | Agent B | Four normalized source summaries already available |
| 2 | Default Executive Grafana dashboard | Agent B | Agent A | Milestone 1 merged |
| 3A | Device correlation | Agent A | Agent B | Milestone 1 merged |
| 3B | Cross-source integration health aggregation | Agent B | Agent A | 3A shared contract/database changes merged first if any |
| 4 | Grafana provisioning/reference standardization | Agent B | Agent A | Milestone 2 merged |
| 5A | Local AI runtime and bounded backend orchestration | Agent A | Agent B | Executive/correlation/health contracts stable |
| 5B | Executive AI visualization/summary integration | Agent B | Agent A | 5A API contract merged |
| 6 | Internal HTTPS/reverse-proxy deployment model | Agent B | Agent A | 5A deployment/runtime changes merged |
| 7A | End-to-end API acceptance and backup/restore procedure | Agent A | Agent B | Functional milestones complete |
| 7B | Grafana/operations acceptance and handover documentation | Agent B | Agent A | Functional milestones complete |
| 7C | Final joint release review | Both, sequential review only | User/coordinator approves | 7A and 7B complete |

The primary implementer owns the shared write lock for that milestone. The reviewer should inspect and review but must not modify the same shared files concurrently.

## Milestone 1: Shared Executive Aggregator/API

### Agent A write zone

Expected shared write zone:

- new `app/dashboard/executive/**` package if needed;
- shared Executive response contracts under `app/contracts/**` only when required;
- shared router/application registration only where required;
- new Executive tests;
- no source-owned adapter edits unless the affected source is Wazuh or Freshservice and the change is separately justified.

### Agent B role

Agent B reviews the normalized contract and tests. Agent B must not edit the Executive shared files while Agent A owns this milestone.

If Zabbix or Snipe-IT needs adaptation, Agent B makes that source-owned change in a separate follow-up branch after the shared contract is merged.

### Required behavior

- Consume normalized `ExecutiveSourceSummary` values only.
- Do not parse Wazuh, Freshservice, Zabbix, or Snipe-IT raw API responses.
- One failed, stale, empty, unavailable, or not-configured source must not break unrelated summaries.
- Preserve the canonical integration health states and safe warnings.
- Add tests before or with implementation for mixed health conditions.

## Milestone 2: Executive Grafana Dashboard

### Agent B write zone

Expected write zone:

- new `grafana/dashboards/executive.json`;
- Executive-specific Grafana reference/provisioning files when required;
- Grafana documentation directly related to the Executive dashboard.

### Agent A role

Agent A reviews the dashboard against the merged Executive API contract. Agent A must not concurrently edit the Executive dashboard JSON.

### Constraint

Grafana must visualize the Executive API. It must not reproduce backend business logic, parse raw source APIs, or calculate a conflicting definition of health/counts.

## Milestone 3A: Device Correlation

### Agent A write zone

Expected write zone:

- new `app/correlation/**`;
- correlation-specific shared contracts;
- correlation models/migrations if approved and required;
- correlation tests.

### Constraints

- Source integrations remain read-only.
- Canonical identity should use approved identifiers such as manual mapping, exact serial/asset tag, normalized hostname, stable IP, and bounded combined evidence.
- Do not rewrite source-specific normalization solely to make correlation easier.
- If a database migration is required, Agent A owns the migration lock until the migration is merged.

## Milestone 3B: Integration Health Aggregation

### Agent B write zone

Expected write zone:

- new `app/integrations/health/**`;
- health aggregation tests;
- shared health contract changes only after any 3A shared changes are merged and Agent B has updated from `main`.

### Constraints

- Aggregate existing source health/freshness information.
- Do not make one unavailable source turn the whole API into an application failure.
- Do not modify source-owned health behavior directly; request a source-owner fix if a source violates the agreed shared contract.

## Milestone 4: Grafana Provisioning Standardization

### Agent B write zone

Expected write zone:

- `grafana/provisioning/**`;
- `grafana/README.md` when required;
- shared Grafana reference configuration only.

### Constraints

- Preserve the host-installed Grafana deployment model.
- Do not introduce a second Grafana container unless the architecture is explicitly changed.
- Do not rewrite the Wazuh/Freshservice source dashboards during this task.
- Do not hard-code environment-specific datasource UIDs when a reusable input/variable pattern exists.
- Never expose datasource credentials or secure fields.

## Milestone 5A: Local AI Runtime and Backend Orchestration

### Agent A write zone

Expected write zone:

- new local AI runtime/orchestration package;
- bounded shared AI contracts;
- authenticated AI API routes if required;
- runtime configuration required for the approved local model;
- tests covering prompt/data boundaries, unavailable model behavior, and source isolation.

### Constraints

- Fully local execution only.
- No cloud AI fallback.
- No monitoring, asset, ticket, or security evidence may leave the company network.
- AI output is explanatory/investigative only and must not execute remediation.
- Do not add source writes, remote commands, service control, or automatic Freshservice changes.
- Changes to `compose.yaml`, `.env.example`, `pyproject.toml`, or `uv.lock` are part of Agent A's temporary shared-file lock for this milestone.

## Milestone 5B: Executive AI Visualization

### Agent B write zone

Expected write zone:

- Executive dashboard AI panels/summary visualization;
- Executive-only Grafana changes that consume the stable 5A API.

### Constraint

Do not duplicate AI orchestration inside Grafana. Grafana only displays bounded API output.

If source-specific AI panels are later approved, each source owner modifies only that owner's source dashboard in separate branches.

## Milestone 6: Internal HTTPS / Reverse Proxy

### Agent B write zone

Expected write zone:

- approved reverse-proxy configuration;
- deployment documentation;
- `compose.yaml`/deployment files only as required;
- TLS-related configuration templates that contain no secrets.

### Constraints

- Internal company-network exposure only.
- Do not disable authentication or TLS verification.
- Do not commit private keys, certificates containing private material, passwords, or tokens.
- Do not broaden firewall/network exposure as part of repository work.
- Any live service restart, firewall, DNS, routing, or system-level change requires separate explicit user permission.

## Milestone 7: Acceptance, Backup/Restore, and Handover

### Agent A

Primary for:

- API and integration end-to-end acceptance coverage;
- database/application backup and restore procedure;
- backend operational verification steps.

### Agent B

Primary for:

- Grafana acceptance checks;
- deployment/operator reference documentation;
- dashboard/handover procedure.

### Final joint review

Both agents review sequentially rather than editing the same files together. The final release review must confirm:

- intended source integrations remain read-only;
- all required tests pass;
- Compose/configuration validation passes;
- migration history has one expected head unless deliberately designed otherwise;
- no secrets are tracked;
- dashboards consume canonical API behavior;
- degraded/unavailable source behavior is documented and tested;
- backup/restore instructions are tested or clearly marked unverified;
- final diffs contain no unrelated changes.

## Dedicated Worktree and Branch Rules

Each AI agent must use its own branch and worktree for active implementation.

Rules:

1. Never let both agents modify the same physical worktree.
2. Never check out another agent's active branch in your worktree.
3. Use one branch for one logical task.
4. Start new feature branches from an updated `main`/`origin/main`.
5. Do not continue a dependent shared task from an old baseline after its prerequisite merged.
6. Do not force-push a shared/reviewed branch.
7. Do not commit directly to `main`.
8. Do not delete another agent's branch or worktree.
9. Worktree cleanup happens only after merge verification and explicit deletion approval.

Suggested branch names:

- `feature/executive-api`
- `feature/executive-dashboard`
- `feature/device-correlation`
- `feature/integration-health`
- `chore/grafana-provisioning`
- `feature/local-ai-backend`
- `feature/executive-ai-summary`
- `feature/internal-https`
- `test/end-to-end-acceptance`
- `docs/operations-handover`

## Required AI-Agent Start Protocol

Before making any change, each AI agent must:

1. Inspect the current branch and working-tree status.
2. Fetch/check the latest remote state when remote access is available.
3. Confirm the task branch is based on the intended current `main`.
4. Read `AGENTS.md`, `docs/development/collaboration-rules.md`, and this document.
5. Inspect the relevant implementation before proposing edits.
6. State the intended write set: the files/directories it expects to modify.
7. Confirm the write set does not overlap the other agent's active task.
8. If shared paths are needed, confirm that this task owns the shared write lock.
9. Write or update focused tests before/with implementation as appropriate.
10. Make only the smallest required change.

An AI agent must not infer permission to modify unrelated files from permission granted for a different task.

## Unexpected Cross-Boundary Change Rule

If an agent discovers that its task requires a file outside its approved write zone:

1. Do not edit the file yet.
2. Report why the additional file is required.
3. Identify its current owner/shared-lock status.
4. Decide whether the change can be avoided through the existing interface.
5. If it cannot be avoided, get an explicit ownership/assignment decision.
6. Update/rebase the affected branch after any prerequisite shared change is merged.

This rule applies even when the additional edit appears small.

## Shared Contract Change Protocol

When a cross-source interface must change:

1. Define the contract change before modifying source adapters.
2. Assign one primary implementer for `app/contracts/**` and related shared tests.
3. Merge the shared contract change first.
4. Agent A updates Wazuh/Freshservice only if those sources need adaptation.
5. Agent B updates Zabbix/Snipe-IT only if those sources need adaptation.
6. Merge source adaptations separately.
7. Only then continue the shared consumer feature if it depends on those adaptations.

Never have both agents modify `app/contracts/**` in parallel.

## Migration Lock

Only one migration-producing task may be active at a time.

Before creating a migration:

1. Inspect the current Alembic head.
2. Confirm no other active branch is creating a migration.
3. The assigned migration owner creates the next revision.
4. Merge and verify that revision.
5. The next migration-producing task updates from `main` before creating another revision.

Never edit an already merged migration for a new feature.

## Dependency and Lock-File Rule

Only the task that currently owns `pyproject.toml`/`uv.lock` may add, remove, or upgrade Python dependencies.

If the other task also needs a dependency change, it waits until the first dependency-changing branch is merged and then updates from `main`.

Package installation or dependency changes still require explicit user permission under the project operating rules.

## Database and Production-Data Rule

Repository schema/code changes and live database/data changes are separate permissions.

An approved code task does not automatically authorize:

- modifying production rows;
- deleting synchronized data;
- rebuilding indexes/data stores;
- applying migrations to a live environment;
- changing database users/credentials;
- destructive database commands.

Obtain explicit permission before any production-affecting database operation.

## System and Infrastructure Permission Boundary

Repository modification permission does not authorize system-level changes.

Explicit user permission is required before:

- `sudo` or elevated commands;
- installing/upgrading/removing system packages;
- starting, stopping, restarting, reloading, or enabling services;
- changing Wazuh/Zabbix/Grafana/Snipe-IT/Freshservice live configuration;
- changing firewall/UFW rules;
- changing networking, DNS, routing, interfaces, or Tailscale;
- changing users, groups, ownership, or permissions;
- changing systemd units;
- deleting files or live data;
- changing live dashboards, alerts, rules, indexes, or production data.

Safe reads and non-destructive diagnostics may be performed without modification permission unless elevated privileges are required.

## Git Conflict Rules

If a merge/rebase conflict occurs:

- Do not automatically choose `ours` or `theirs` for shared files.
- Do not overwrite another agent's work to make the conflict disappear.
- Inspect both sides and the merged contract first.
- Preserve unrelated changes from both branches.
- Re-run the relevant focused tests after resolution.
- Run the full available suite before merge.
- Review `git diff`/`git diff --check` before reporting success.

If the conflict involves a source-owned integration, the source owner decides the source-specific resolution. If it involves a shared contract, both agents review the resolution before merge.

## Parallel Work Allowed

Parallel work is allowed only when write sets are clearly disjoint. Examples:

- Agent A Wazuh/Freshservice maintenance while Agent B works only in Zabbix/Snipe-IT.
- Agent A device-correlation implementation while Agent B performs Grafana provisioning work, provided neither branch touches the same shared contracts, database files, root configuration, or coordination docs.
- One agent implementing while the other performs read-only review/research.

When uncertain whether write sets overlap, treat the tasks as conflicting and run them sequentially.

## Parallel Work Not Allowed

Do not run these concurrently when both require shared edits:

- two Executive API/shared-contract changes;
- two migration-producing tasks;
- two dependency/lock-file changes;
- AI runtime changes and HTTPS/deployment changes when both touch `compose.yaml` or `.env.example`;
- Executive dashboard work by two agents on the same JSON;
- two Grafana provisioning changes on the same provisioning files;
- any two tasks that both need `app/main.py`, `app/worker.py`, `app/db/**`, or `app/contracts/**`.

## Validation Before Handoff or Merge

The task owner must validate changes before handing them to the reviewer.

Minimum validation:

1. Focused tests for the changed behavior.
2. Full available test suite.
3. Flake8/linting for Python changes.
4. `git diff --check`.
5. Compose validation when Compose/deployment files change.
6. Alembic head/configuration validation when migrations change.
7. JSON validation for dashboard files.
8. Secret review for configuration/deployment changes.
9. Final diff review confirming only intended files changed.

Do not report a task as fixed or complete if its relevant validation has not passed. If runtime validation cannot be performed, state exactly what remains unverified.

## Handoff Format Between Agents

When one agent finishes a task that another task depends on, provide this handoff information:

- task/milestone name;
- branch name;
- commit or merge commit after merge;
- files changed;
- shared contracts added/changed;
- migrations added;
- configuration/dependency changes;
- validation commands and results;
- known limitations;
- exact next task that is now unblocked.

The dependent agent must update from the merged `main` before starting implementation.

## Merge Gate

A branch may be merged only when:

- ownership boundaries were respected;
- no unapproved cross-source edits are present;
- required tests pass;
- full available tests pass;
- lint/configuration checks pass;
- secrets are absent;
- migration/dependency changes are coordinated;
- final diff is scoped to the task;
- the reviewer has reviewed shared architectural changes;
- runtime-impacting changes have the required user permission.

## Original Recommended Execution Order

This was the default implementation sequence. The repository-level milestones in this sequence are now implemented or prepared as described in the current-status section above:

```text
1. Agent A: Executive aggregator/API
        |
        v
2. Agent B: Executive Grafana dashboard
        |
        +---------------------------+
        |                           |
        v                           v
3A. Agent A: Device correlation     4. Agent B: Grafana provisioning
        |
        v
3B. Agent B: Integration health
        |
        v
5A. Agent A: Local AI backend/orchestration
        |
        v
5B. Agent B: Executive AI visualization
        |
        v
6. Agent B: Internal HTTPS/reverse proxy
        |
        v
7A. Agent A: API acceptance + backup/restore
7B. Agent B: Grafana/ops acceptance + handover
        |
        v
7C. Joint sequential final review
```

The only planned parallel pair in the original sequence was **3A device correlation** and **4 Grafana provisioning**, and only when their actual write sets were disjoint after inspection. For new work, keep using the same conflict-prevention rule: parallel changes are allowed only when write sets are clearly disjoint.

## Stop Conditions

An AI agent must stop modification and report before continuing if:

- another active task already owns a required shared file;
- the branch is not based on the expected merged prerequisite;
- an unexpected migration is required while another migration task is active;
- a source-owned package outside the agent's ownership must change;
- a dependency or deployment change requires permission not yet granted;
- a live/system change would be required;
- secrets appear in a proposed diff or log output;
- tests reveal a cross-source contract incompatibility;
- resolving a conflict would require discarding another agent's work.

The purpose of stopping is to coordinate the boundary before conflict is created, not after.
