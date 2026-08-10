# Collaboration Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add enforceable repository collaboration guidance and small source-neutral integration/Executive contracts so two interns can develop Wazuh/Freshservice and Zabbix/Snipe-IT independently without coupling the Executive dashboard to raw source payloads.

**Architecture:** Keep source implementations isolated behind `app/integrations/<source>/` ownership boundaries. Add repository-level human/agent rules plus a focused `app/contracts/` package containing only Pydantic data contracts; the shared Executive layer will later consume these contracts instead of source-specific responses. This plan does not implement any external API adapter, database migration, dashboard, Compose service, or runtime integration.

**Tech Stack:** Python 3.12, FastAPI project conventions, Pydantic v2 (already provided by FastAPI/pydantic-settings), pytest, Git/Markdown governance files.

## Global Constraints

- Intern A owns Wazuh and Freshservice ITSM implementation, tests, and source dashboards.
- Intern B owns Zabbix and Snipe-IT implementation, tests, and source dashboards.
- The Executive dashboard and cross-source platform contracts are shared ownership.
- Source integrations remain read-only and internal-network only.
- No monitoring, asset, or ticket data may leave the company network.
- The Executive dashboard must consume normalized source summaries, never raw source API responses.
- Shared architectural files are changed by one active implementer at a time and reviewed by the other intern before integration into `main`.
- Do not create or guess `.github/CODEOWNERS` entries until verified GitHub review handles for both interns are available.
- Integration-specific environment variables must use `WAZUH_`, `FRESHSERVICE_`, `ZABBIX_`, or `SNIPE_IT_` prefixes.
- Secrets, credentials, authorization data, private keys, and production connection strings must never be committed or logged.
- Never edit an already merged Alembic migration to add a new feature; shared migration work must inspect and coordinate the current migration head.
- Keep this implementation limited to collaboration controls and shared contracts; do not begin Wazuh, Freshservice, Zabbix, Snipe-IT, Grafana, AI, or Executive aggregation implementation.

---

## File Structure

Create the following focused files:

```text
AGENTS.md
  Repository-root instructions for humans and coding agents. Short, imperative,
  and security-sensitive; points to the detailed collaboration document.

docs/development/collaboration-rules.md
  Human-readable ownership matrix, branch/PR workflow, shared-change protocol,
  migration/configuration rules, testing responsibilities, and definition of done.

app/contracts/__init__.py
  Public exports for shared contract types only.

app/contracts/integration.py
  Source-neutral Pydantic types for integration identity/health and Executive
  source-summary envelopes. No clients, network code, persistence, or source-specific fields.

tests/test_collaboration_policy.py
  Lightweight regression checks that the repository governance files retain the
  required ownership/security/Executive-boundary statements.

tests/test_integration_contracts.py
  Contract validation tests for canonical source/status values, scalar-only KPI
  metrics, bounded payloads, matching source identities, and extra-field rejection.
```

Do not create `.github/CODEOWNERS` in this implementation. Activation is a later shared governance change after both verified GitHub review handles are known.

---

### Task 1: Repository collaboration policy

**Files:**
- Create: `AGENTS.md`
- Create: `docs/development/collaboration-rules.md`
- Create: `tests/test_collaboration_policy.py`

**Interfaces:**
- Consumes: approved design in `docs/superpowers/specs/2026-08-10-two-intern-collaboration-controls-design.md`.
- Produces: repository-wide ownership/safety instructions and a human collaboration procedure referenced by future development work.

- [ ] **Step 1: Write the failing policy regression tests**

Create `tests/test_collaboration_policy.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_agents_file_enforces_domain_ownership_and_shared_executive_boundary() -> None:
    text = (ROOT / "AGENTS.md").read_text()

    assert "Wazuh and Freshservice" in text
    assert "Zabbix and Snipe-IT" in text
    assert "Executive dashboard" in text
    assert "raw source" in text
    assert "read-only" in text
    assert "CODEOWNERS" in text
    assert "verified GitHub" in text


def test_human_collaboration_rules_define_shared_change_protocol() -> None:
    text = (ROOT / "docs/development/collaboration-rules.md").read_text()

    assert "Ownership Matrix" in text
    assert "Shared-Change Protocol" in text
    assert "Migration Coordination" in text
    assert "Definition of Done" in text
    assert "WAZUH_" in text
    assert "FRESHSERVICE_" in text
    assert "ZABBIX_" in text
    assert "SNIPE_IT_" in text
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_collaboration_policy.py
```

If the project-local environment does not contain the project dependencies, reconcile it first with the existing project metadata:

```bash
uv pip install --python .venv/bin/python -e '.[dev]'
```

Then rerun the focused test.

Expected: FAIL with `FileNotFoundError` for `AGENTS.md` and/or `docs/development/collaboration-rules.md` because the governance files do not exist yet.

- [ ] **Step 3: Create the repository-root `AGENTS.md`**

Create a concise imperative file with these exact policy sections and rules:

```markdown
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
```

Do not duplicate the full architecture specification in `AGENTS.md`; keep the file operational and easy for coding agents to follow.

- [ ] **Step 4: Create the detailed human collaboration document**

Create `docs/development/collaboration-rules.md` with the following sections and content:

```markdown
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

Intern A owns `app/integrations/wazuh/`, `app/integrations/freshservice/`, their tests, and their source dashboards. Intern B owns the corresponding Zabbix and Snipe-IT paths. Shared paths include `app/contracts/`, `app/core/`, `app/db/`, `app/dashboard/executive/`, `app/integrations/health/`, `app/normalization/`, `app/correlation/`, `migrations/`, Executive Grafana provisioning, `compose.yaml`, `Dockerfile`, `.env.example`, and `pyproject.toml`.

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

Changes to another intern's owned domain require that owner's review. Shared architectural changes require review from both interns before merge.

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
```

- [ ] **Step 5: Run focused policy tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_collaboration_policy.py
```

Expected: `2 passed`.

- [ ] **Step 6: Review the policy diff for accidental scope expansion**

Run:

```bash
git diff -- AGENTS.md docs/development/collaboration-rules.md tests/test_collaboration_policy.py
git diff --check
```

Verify there are no source-adapter files, credentials, CODEOWNERS entries, deployment changes, or unrelated edits.

- [ ] **Step 7: Commit Task 1**

```bash
git add AGENTS.md docs/development/collaboration-rules.md tests/test_collaboration_policy.py
git commit -m "docs: add two-intern collaboration controls"
```

---

### Task 2: Shared integration and Executive summary contracts

**Files:**
- Create: `app/contracts/__init__.py`
- Create: `app/contracts/integration.py`
- Create: `tests/test_integration_contracts.py`

**Interfaces:**
- Consumes: Pydantic v2 already available through the project dependencies.
- Produces: `IntegrationSource`, `IntegrationStatus`, `IntegrationHealthSummary`, `ExecutiveMetricValue`, and `ExecutiveSourceSummary` exported from `app.contracts`.
- Future integration owners construct these models; future Executive aggregation code consumes them without importing source-specific payload models.

- [ ] **Step 1: Write failing contract tests**

Create `tests/test_integration_contracts.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def test_integration_health_accepts_canonical_values_and_rejects_extra_fields() -> None:
    from app.contracts import IntegrationHealthSummary

    health = IntegrationHealthSummary(
        source="wazuh",
        status="healthy",
        observed_at=NOW,
        last_success_at=NOW,
        response_time_ms=42,
        is_stale=False,
        warnings=[],
    )

    assert health.source == "wazuh"
    assert health.status == "healthy"

    with pytest.raises(ValidationError):
        IntegrationHealthSummary(
            source="wazuh",
            status="healthy",
            observed_at=NOW,
            is_stale=False,
            warnings=[],
            raw_response={"do_not": "store this"},
        )


def test_integration_health_rejects_unknown_source_and_status() -> None:
    from app.contracts import IntegrationHealthSummary

    with pytest.raises(ValidationError):
        IntegrationHealthSummary(
            source="unknown",
            status="healthy",
            observed_at=NOW,
            is_stale=False,
        )

    with pytest.raises(ValidationError):
        IntegrationHealthSummary(
            source="wazuh",
            status="broken",
            observed_at=NOW,
            is_stale=False,
        )


def test_executive_summary_accepts_scalar_metrics_only() -> None:
    from app.contracts import ExecutiveSourceSummary, IntegrationHealthSummary

    health = IntegrationHealthSummary(
        source="freshservice",
        status="degraded",
        observed_at=NOW,
        last_success_at=NOW,
        response_time_ms=150,
        is_stale=True,
        warnings=["Ticket data is stale."],
    )

    summary = ExecutiveSourceSummary(
        source="freshservice",
        observed_at=NOW,
        is_stale=True,
        health=health,
        metrics={
            "open_tickets": 12,
            "sla_risk": 3,
            "availability_note": "partial",
            "has_critical_ticket": True,
            "optional_value": None,
        },
        warnings=["Ticket data is stale."],
    )

    assert summary.metrics["open_tickets"] == 12

    with pytest.raises(ValidationError):
        ExecutiveSourceSummary(
            source="freshservice",
            observed_at=NOW,
            is_stale=True,
            health=health,
            metrics={"raw_tickets": [{"id": 1}]},
        )


def test_executive_summary_rejects_source_mismatch_and_unbounded_metrics() -> None:
    from app.contracts import ExecutiveSourceSummary, IntegrationHealthSummary

    health = IntegrationHealthSummary(
        source="zabbix",
        status="healthy",
        observed_at=NOW,
        is_stale=False,
    )

    with pytest.raises(ValidationError, match="health source"):
        ExecutiveSourceSummary(
            source="wazuh",
            observed_at=NOW,
            is_stale=False,
            health=health,
            metrics={},
        )

    with pytest.raises(ValidationError):
        ExecutiveSourceSummary(
            source="zabbix",
            observed_at=NOW,
            is_stale=False,
            health=health,
            metrics={f"metric_{index}": index for index in range(33)},
        )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_integration_contracts.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.contracts'`.

- [ ] **Step 3: Implement the minimal source-neutral contract module**

Create `app/contracts/integration.py`:

```python
from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)


IntegrationSource: TypeAlias = Literal["wazuh", "zabbix", "snipe_it", "freshservice"]
IntegrationStatus: TypeAlias = Literal["healthy", "degraded", "unavailable", "not_configured"]

WarningText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
MetricKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
ExecutiveMetricValue: TypeAlias = StrictBool | StrictInt | StrictFloat | StrictStr | None


class IntegrationHealthSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: IntegrationSource
    status: IntegrationStatus
    observed_at: datetime
    last_success_at: datetime | None = None
    response_time_ms: int | None = Field(default=None, ge=0)
    is_stale: bool = False
    warnings: list[WarningText] = Field(default_factory=list, max_length=20)


class ExecutiveSourceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: IntegrationSource
    observed_at: datetime
    is_stale: bool = False
    health: IntegrationHealthSummary
    metrics: dict[MetricKey, ExecutiveMetricValue] = Field(default_factory=dict, max_length=32)
    warnings: list[WarningText] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_health_source(self) -> "ExecutiveSourceSummary":
        if self.health.source != self.source:
            raise ValueError("health source must match Executive summary source")
        return self
```

Create `app/contracts/__init__.py`:

```python
from app.contracts.integration import (
    ExecutiveMetricValue,
    ExecutiveSourceSummary,
    IntegrationHealthSummary,
    IntegrationSource,
    IntegrationStatus,
)

__all__ = [
    "ExecutiveMetricValue",
    "ExecutiveSourceSummary",
    "IntegrationHealthSummary",
    "IntegrationSource",
    "IntegrationStatus",
]
```

Do not add source-specific models, clients, HTTP methods, database models, or environment configuration to `app/contracts/`.

- [ ] **Step 4: Run focused contract tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_integration_contracts.py
```

Expected: `4 passed`.

If a test reveals that Pydantic accepts a nested metric value through coercion, tighten `ExecutiveMetricValue` or the model validation rather than weakening the test. The contract must reject dictionaries and lists.

- [ ] **Step 5: Run all collaboration-focused tests together**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_collaboration_policy.py tests/test_integration_contracts.py
```

Expected: `6 passed`.

- [ ] **Step 6: Run the existing full Python test suite**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app
```

Expected: existing 26 tests plus the 6 new tests pass, for **32 total tests**, and `compileall` exits 0.

- [ ] **Step 7: Review contract/public-API diff**

Run:

```bash
git diff -- app/contracts tests/test_integration_contracts.py
git diff --check
```

Verify:

- source identifiers are exactly `wazuh`, `zabbix`, `snipe_it`, `freshservice`;
- health states are exactly `healthy`, `degraded`, `unavailable`, `not_configured`;
- extra fields are forbidden;
- Executive metrics accept only scalar values or `null`;
- no raw response field exists;
- no network/database/source-specific code was added.

- [ ] **Step 8: Commit Task 2**

```bash
git add app/contracts/__init__.py app/contracts/integration.py tests/test_integration_contracts.py
git commit -m "feat(shared): add integration summary contracts"
```

---

## Final Validation and Review

After both tasks are committed, run the release checks from the repository root:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app
git diff --check main...HEAD
git status --short --branch
git diff --name-status main...HEAD
git log --oneline --decorate main..HEAD
```

Expected final state:

- **32 tests pass** (26 existing + 6 new).
- Python compilation exits 0.
- `git diff --check main...HEAD` exits 0.
- Working tree is clean.
- Changed implementation files are limited to:
  - `AGENTS.md`
  - `docs/development/collaboration-rules.md`
  - `app/contracts/__init__.py`
  - `app/contracts/integration.py`
  - `tests/test_collaboration_policy.py`
  - `tests/test_integration_contracts.py`
  - plus the already-approved collaboration design and this implementation plan on the planning branch.
- No `.github/CODEOWNERS` exists as a result of this work unless both verified GitHub review handles were separately supplied and explicitly approved in a later shared-governance change.
- No Wazuh, Freshservice, Zabbix, Snipe-IT, Grafana, AI, database migration, authentication, Compose, firewall, networking, or service behavior changes are present.

Review for secrets before reporting completion. Do not merge or push automatically; integration remains a user choice after validation.
