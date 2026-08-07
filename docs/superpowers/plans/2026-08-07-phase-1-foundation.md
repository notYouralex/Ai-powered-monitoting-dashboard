# Phase 1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a secure, testable FastAPI/PostgreSQL foundation with local administrator-managed accounts, server-side sessions, audit logging, and container deployment scaffolding.

**Architecture:** Keep the approved modular-monolith boundary: one FastAPI package with focused core/auth modules and a synchronous SQLAlchemy persistence layer. Authentication uses Argon2id password hashes plus random opaque session tokens; only SHA-256 token digests are stored. PostgreSQL is the production database, while unit/API tests use isolated SQLite databases through the same ORM models.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL, argon2-cffi, pydantic-settings, pytest/httpx, Docker Compose.

## Global Constraints

- Internal company-network access only; no public internet exposure.
- Monitoring, asset, and ticket data must not leave the company network.
- Source integrations remain read-only; Phase 1 adds no source-system writes.
- Secrets are loaded from environment variables or protected files excluded from Git.
- Never log credentials, authorization headers, password hashes, connection strings, or unnecessary sensitive content.
- Safe errors must not expose stack traces or secrets.
- Development VM baseline: Ubuntu, 4 CPU cores, about 10 GB RAM, no GPU; current repository runtime is Python 3.12.3.
- Preserve the existing uncommitted edit in `docs/superpowers/specs/2026-08-06-ai-powered-monitoring-platform-design.md`.

---

### Task 1: Application and configuration skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `app/__init__.py`
- Create: `app/main.py`
- Create: `app/core/__init__.py`
- Create: `app/core/config.py`
- Test: `tests/test_health.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `app.main.create_app() -> FastAPI`
- Produces: `app.core.config.Settings` and cached `get_settings()`

- [ ] Write API/config tests first: `/health` returns `{"status":"ok"}` and production-like configuration rejects a missing/placeholder secret.
- [ ] Run the focused tests and confirm RED because the application package does not exist.
- [ ] Add the minimal package, settings model, dependency metadata, ignored secret/runtime files, and health endpoint.
- [ ] Run the focused tests and full test set until GREEN.
- [ ] Commit only Task 1 files.

### Task 2: Database models and migrations

**Files:**
- Create: `app/db/__init__.py`
- Create: `app/db/base.py`
- Create: `app/db/session.py`
- Create: `app/db/models.py`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/0001_auth_foundation.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Base`, `User`, `AuthSession`, `AuthAuditEvent`, `LoginAttempt`.
- Produces: `get_db()` and `create_engine_for_url(url)`.

- [ ] Write model tests first for unique usernames, inactive/admin state, hashed session-token storage fields, expiry/last-seen timestamps, and audit/login-attempt records.
- [ ] Confirm RED before creating ORM models.
- [ ] Implement SQLAlchemy models with timezone-aware UTC timestamps and indexes needed for session lookup and login throttling.
- [ ] Add an Alembic migration matching the model schema.
- [ ] Run tests and `alembic upgrade head` against a temporary SQLite database to confirm GREEN/migration validity.
- [ ] Commit only Task 2 files.

### Task 3: Authentication service and API

**Files:**
- Create: `app/auth/__init__.py`
- Create: `app/auth/security.py`
- Create: `app/auth/service.py`
- Create: `app/auth/dependencies.py`
- Create: `app/auth/router.py`
- Modify: `app/main.py`
- Test: `tests/conftest.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Produces: `hash_password(password)`, `verify_password(password, password_hash)` using Argon2id.
- Produces: server-side session creation/validation/revocation using a random opaque cookie token and SHA-256 token digest storage.
- Produces endpoints: `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`.

- [ ] Write failing API tests for successful login, invalid credentials, inactive users, session expiry/inactivity, logout revocation, safe unauthenticated errors, and cookie flags.
- [ ] Confirm RED for each behavior before implementation.
- [ ] Implement password verification and opaque session generation; never persist raw session tokens.
- [ ] Implement database-backed login throttling and authentication auditing without logging passwords/tokens.
- [ ] Implement auth dependencies and API routes; refresh `last_seen_at` only at a bounded interval to avoid a write on every request.
- [ ] Run auth tests and full tests until GREEN.
- [ ] Commit only Task 3 files.

### Task 4: Administrator-managed accounts

**Files:**
- Create: `app/auth/schemas.py`
- Create: `app/auth/admin_router.py`
- Create: `app/cli.py`
- Modify: `app/main.py`
- Test: `tests/test_admin.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `POST /api/admin/users` requiring an authenticated active administrator.
- Produces: `python -m app.cli create-admin --username NAME`, reading the password with `getpass` rather than command-line arguments.

- [ ] Write failing tests proving normal users cannot create accounts, admins can create users, duplicate usernames are rejected safely, password hashes are never returned, and account creation is audited.
- [ ] Write a failing CLI test proving bootstrap-admin creation does not accept a password command-line option.
- [ ] Implement minimal schemas, admin dependency/router, and bootstrap CLI.
- [ ] Run focused and full tests until GREEN.
- [ ] Commit only Task 4 files.

### Task 5: Deployment scaffold and release validation

**Files:**
- Create: `Dockerfile`
- Create: `compose.yaml`
- Create: `docker/entrypoint.sh`
- Modify: `README.md`
- Test: `tests/test_deployment_files.py`

**Interfaces:**
- Compose services for this phase: `fastapi-api`, `postgresql`; later phases add worker, Grafana, local AI, and reverse proxy.
- API binds inside the container; host exposure defaults to loopback for development rather than all interfaces.

- [ ] Write static deployment tests first for non-root application execution, no hard-coded secrets, PostgreSQL healthcheck, secret/config interpolation, and loopback-only development port binding.
- [ ] Confirm RED because deployment files are absent.
- [ ] Add a small Python image, unprivileged runtime user, migration-before-start entrypoint, PostgreSQL volume/healthcheck, and environment-driven configuration.
- [ ] Document local setup, admin bootstrap, test commands, and the Phase 1 security boundary in README.
- [ ] Run `pytest`, `python -m compileall app`, Alembic migration checks, `docker compose config`, and a Docker build if dependency/network access permits.
- [ ] Review `git diff`/`git status` to ensure the pre-existing spec modification is untouched and no secrets are present.
- [ ] Commit only Task 5 files and perform final read-only validation.
