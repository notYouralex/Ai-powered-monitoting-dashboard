# Shared Integration Foundation — Design

**Date:** 2026-08-10
**Status:** Approved
**Applies to:** AI-Powered Monitoring Dashboard repository
**Scope:** Minimal shared integration foundation (Scope A)

## 1. Goal

Create the smallest shared integration foundation needed for Intern A to begin Wazuh development and Intern B to begin Zabbix development without duplicating or conflicting on configuration, HTTP transport, request tracing, safe source errors, dependency setup, or FastAPI router wiring.

This milestone remains infrastructure-only. It does not implement source retrieval, authentication flows, normalization, dashboards, synchronization, database persistence, correlation, AI, or production deployment changes.

The existing architecture and security rules remain fixed:

- source integrations are read-only;
- source-specific API formats stop inside the owning integration package;
- no monitoring, asset, or ticket data leaves the company network;
- TLS verification is enabled by default and is never disabled automatically;
- secrets are not committed, logged, or returned in API errors;
- one missing or unavailable source must not prevent the application or unrelated sources from operating.

## 2. Selected Approach

Use a thin shared foundation rather than a shared base-adapter hierarchy.

Shared code owns only cross-cutting transport and application behavior:

- dependency/runtime reproducibility;
- source-prefixed configuration;
- HTTP client construction and bounded transport policy;
- narrowly opt-in retry behavior;
- request IDs;
- safe integration error representation and FastAPI handling;
- integration package and router boundaries.

Source packages own source semantics such as authentication, endpoint paths, pagination, response parsing, normalization, and health checks.

This avoids forcing Wazuh REST/JWT, Zabbix JSON-RPC/token, Snipe-IT bearer-token, and Freshservice API-key behavior into one inheritance model.

## 3. Target Package Structure

```text
app/
├── core/
│   ├── config.py
│   ├── errors.py
│   ├── http.py
│   └── request_id.py
├── contracts/
│   └── integration.py
└── integrations/
    ├── __init__.py
    ├── router.py
    ├── wazuh/
    │   ├── __init__.py
    │   └── router.py
    ├── zabbix/
    │   ├── __init__.py
    │   └── router.py
    ├── snipe_it/
    │   ├── __init__.py
    │   └── router.py
    └── freshservice/
        ├── __init__.py
        └── router.py
```

The source routers are intentionally minimal in this milestone. `app/integrations/router.py` is mounted once by `app/main.py`, so later source feature branches can normally add endpoints inside their owned packages without repeatedly modifying application bootstrap code.

## 4. Dependency and Environment Reproducibility

`httpx` becomes a normal runtime dependency because all four source adapters require HTTP communication. `pytest` remains development-only.

The repository gains a committed `uv.lock`. The intended local workflow becomes:

```bash
uv sync --extra dev --frozen
.venv/bin/python -m pytest -q
```

The local `.venv` remains ignored and is synchronized from the lockfile. No dependency setup may require `sudo` or system package changes.

The lockfile records resolved Python dependencies only; it must not contain source credentials or environment-specific secrets.

## 5. Source Configuration

Integration configuration remains optional so FastAPI can start when zero, one, or several sources are unconfigured.

A source is considered configured only when its required connection and authentication fields are present. Otherwise its configuration state is `not_configured`.

Required fields are:

- Wazuh: base URL, username, password;
- Zabbix: base URL, API token;
- Snipe-IT: base URL, API token;
- Freshservice: base URL, API key.

Missing source configuration must not fail global `Settings` construction or application startup. Base URLs must be valid HTTP(S) URLs and must not contain embedded username/password userinfo.

### Shared connection fields

Each source receives source-prefixed values for:

- base URL;
- TLS verification flag, default `true`;
- optional CA bundle/certificate path;
- request timeout, default 10 seconds, accepted range 1–60 seconds.

Environment variables remain unambiguous:

```text
WAZUH_...
ZABBIX_...
SNIPE_IT_...
FRESHSERVICE_...
```

### Authentication placeholders

The configuration model reserves only the authentication mechanism verified for each source:

```text
WAZUH_BASE_URL
WAZUH_USERNAME
WAZUH_PASSWORD
WAZUH_VERIFY_TLS
WAZUH_CA_BUNDLE
WAZUH_TIMEOUT_SECONDS

ZABBIX_BASE_URL
ZABBIX_API_TOKEN
ZABBIX_VERIFY_TLS
ZABBIX_CA_BUNDLE
ZABBIX_TIMEOUT_SECONDS

SNIPE_IT_BASE_URL
SNIPE_IT_API_TOKEN
SNIPE_IT_VERIFY_TLS
SNIPE_IT_CA_BUNDLE
SNIPE_IT_TIMEOUT_SECONDS

FRESHSERVICE_BASE_URL
FRESHSERVICE_API_KEY
FRESHSERVICE_VERIFY_TLS
FRESHSERVICE_CA_BUNDLE
FRESHSERVICE_TIMEOUT_SECONDS
```

The source owners may later add a compatible authentication alternative only when the target source version requires it and the shared-change protocol is followed.

The official source APIs support the selected mechanisms as follows:

- Wazuh server API: username/password authentication obtains a JWT used as a bearer token for subsequent requests.
- Zabbix API: API tokens can be used for authenticated JSON-RPC calls.
- Snipe-IT API: personal API tokens are sent as bearer tokens.
- Freshservice API v2: the API key is used with Basic authentication; password-based account authentication is not used.

Secret fields use Pydantic secret types or equivalent safe representations so ordinary model string/repr output does not reveal their values.

`.env.example` contains names and safe placeholders only. Real values remain in the ignored `.env` or the company-approved secret process.

### TLS rules

TLS verification defaults to enabled for every source.

An explicit CA bundle path is the preferred solution for an internal or self-signed certificate. The foundation never switches verification off because a certificate fails.

Each source retains an explicit `*_VERIFY_TLS` boolean for controlled development, defaulting to `true`. When `APP_ENV=production`, any configured source with `*_VERIFY_TLS=false` must make settings validation fail. The application never changes this value automatically after a certificate error.

## 6. Configuration-State Contract

The shared configuration layer exposes a source-specific configured/not-configured decision without performing network access.

Conceptually:

```text
required fields complete
        |
        v
   configured

required field missing
        |
        v
 not_configured
```

This state is configuration-only. It does not imply the source is reachable or authenticated successfully.

Runtime health (`healthy`, `degraded`, `unavailable`) remains the responsibility of later source health checks using the already-approved `IntegrationHealthSummary` contract.

## 7. Shared HTTP Transport

`app/core/http.py` builds `httpx.AsyncClient` instances with explicit, bounded settings.

The shared layer owns:

- connect/read/write/pool timeouts, all using the selected source timeout value;
- TLS verification or explicit CA bundle selection;
- connection limits of 20 total connections and 10 keep-alive connections per client;
- User-Agent `ai-powered-monitoring-dashboard/0.1`, containing no secrets;
- optional retry execution for operations explicitly marked safe by the caller.

It does not own:

- authentication headers;
- source endpoint paths;
- JSON-RPC construction;
- pagination;
- response normalization;
- source-specific error payload parsing.

### Retry policy

Automatic retry is opt-in, not the default.

A caller may mark an operation retry-safe only when the source owner knows repeating it cannot create a source-side write or other side effect. This is necessary because some read-only APIs, such as Zabbix, use HTTP POST even for read operations.

When retry-safe is enabled, the shared helper allows at most two retries after the initial attempt (three attempts total). Retries are limited to:

- connection establishment failure;
- connection timeout;
- HTTP 429;
- HTTP 502;
- HTTP 503;
- HTTP 504.

Authentication failures, permission failures, malformed requests, and ordinary non-transient 4xx responses are not retried automatically.

Retry delay uses bounded exponential backoff of 0.25 seconds before the first retry and 0.5 seconds before the second. This milestone does not implement an unbounded retry loop, background retry queue, or source-specific `Retry-After` scheduling.

## 8. Request IDs

`app/core/request_id.py` provides middleware that attaches one safe request identifier to every HTTP request.

Behavior:

1. An incoming `X-Request-ID` is reused only when it matches `[A-Za-z0-9._-]{1,64}`.
2. Missing or invalid identifiers are replaced with a lowercase UUID4 hex value.
3. The value is stored on `request.state.request_id`.
4. The response includes `X-Request-ID`.
5. Integration error responses use the same identifier.

Incoming identifiers are length- and character-constrained to prevent log/control-character injection when logging is added later.

## 9. Safe Integration Errors

`app/core/errors.py` provides a source-neutral integration exception and FastAPI exception handler.

The public envelope follows the approved platform shape:

```json
{
  "error": {
    "code": "SOURCE_UNAVAILABLE",
    "message": "Wazuh is temporarily unavailable.",
    "source": "wazuh",
    "retryable": true,
    "request_id": "..."
  }
}
```

The initial shared error codes are intentionally small:

- `SOURCE_NOT_CONFIGURED` — configuration is incomplete; not retryable by the HTTP caller;
- `SOURCE_AUTH_FAILED` — authentication/authorization failed; not automatically retryable;
- `SOURCE_UNAVAILABLE` — source or transport is temporarily unavailable; retryable when appropriate;
- `SOURCE_RATE_LIMITED` — source throttled the request; retryable when appropriate;
- `SOURCE_BAD_RESPONSE` — the source returned an invalid or unusable response; not automatically retryable.

The public message is supplied from a controlled safe message. Raw exception text is not returned to clients.

Initial HTTP status mapping is:

- `SOURCE_NOT_CONFIGURED` -> 503;
- `SOURCE_AUTH_FAILED` -> 502;
- `SOURCE_UNAVAILABLE` -> 503;
- `SOURCE_RATE_LIMITED` -> 503;
- `SOURCE_BAD_RESPONSE` -> 502.

The error `code` remains the authoritative machine-readable reason; the HTTP status only classifies the platform/upstream failure at the transport boundary.

The handler must not expose:

- passwords;
- API keys or bearer/JWT tokens;
- Authorization headers;
- connection strings;
- raw response bodies;
- stack traces;
- source URLs containing embedded credentials.

The source adapter may retain safe internal diagnostic context for later logging, but sensitive values must be redacted before logging is introduced.

## 10. Router Boundary

`app/integrations/router.py` owns the shared integration router and includes the four source routers.

`app/main.py` includes that shared router once.

This milestone does not add functional Wazuh, Zabbix, Snipe-IT, Freshservice, dashboard, or aggregate health endpoints. Empty/minimal source routers exist solely to establish stable ownership boundaries for subsequent feature branches.

Later source feature branches should normally modify only their owned package and tests unless a genuine shared contract change is required.

## 11. Testing Strategy

New tests must prove shared behavior without contacting real source systems.

### Configuration tests

Verify:

- no source credentials configured still allows `Settings` and FastAPI startup;
- incomplete source configuration resolves to `not_configured`;
- complete configuration resolves to configured;
- one source being unconfigured does not affect another source;
- TLS verification defaults to enabled;
- timeouts reject zero/negative or unreasonable values;
- secret representations do not expose credential values;
- production rejects explicitly disabled TLS verification for any configured source.

### HTTP tests

Use `httpx.MockTransport` or equivalent in-process mocks to verify:

- the 10-second default timeout and 1–60 second validation bounds;
- safe User-Agent behavior;
- no authentication is injected by the shared transport;
- retries occur only when explicitly marked safe;
- transient failures are bounded;
- authentication/non-transient 4xx failures are not blindly retried.

### Request-ID/error tests

Verify:

- response request IDs exist;
- valid incoming IDs are preserved;
- invalid incoming IDs are replaced;
- integration errors contain the current request ID;
- the error envelope matches the approved shape;
- internal exception text and seeded fake secrets do not appear in the response.

### Router tests

Verify all four source routers can be imported and mounted through the shared integration router without performing network access or requiring credentials.

### Regression validation

Before merge:

- focused integration-foundation tests pass;
- the complete existing test suite passes;
- `python -m compileall -q app` passes;
- `git diff --check` passes;
- the lockfile is reproducible with `uv sync --extra dev --frozen`;
- Compose configuration remains valid if affected indirectly by dependency changes;
- final diff contains only the approved shared foundation scope;
- no secret-like values are introduced.

## 12. Out of Scope

This milestone explicitly does not implement:

- Wazuh JWT login or any Wazuh data endpoint;
- Zabbix JSON-RPC calls;
- Snipe-IT API calls;
- Freshservice API calls;
- source-specific response models or normalization;
- aggregate `/api/integrations/health` behavior;
- dashboard APIs;
- PostgreSQL integration/cache/sync tables;
- migrations;
- background worker or scheduling;
- Grafana;
- device correlation;
- local AI;
- CI/GitHub Actions;
- CODEOWNERS;
- Docker service additions;
- Wazuh configuration changes;
- service restarts;
- firewall, DNS, routing, Tailscale, or other networking changes.

## 13. Ownership After Merge

After this foundation is merged into `main`:

- Intern A may implement Wazuh inside `app/integrations/wazuh/` and its owned tests without modifying Zabbix/Snipe-IT code.
- Intern B may implement Zabbix inside `app/integrations/zabbix/` and its owned tests without modifying Wazuh/Freshservice code.
- Shared HTTP/config/error behavior is changed only through the shared-change protocol.
- Snipe-IT and Freshservice source implementations remain later work; their package/config boundaries are reserved now to avoid future bootstrap conflicts.

Recommended next branches after the shared foundation is merged:

```text
feature/wazuh-agents
feature/zabbix-hosts
```

## 14. Success Criteria

The milestone is complete when:

1. dependency installation is reproducible from a committed `uv.lock`;
2. `httpx` is available at runtime;
3. all four source configurations can be absent without preventing application startup;
4. each source has an independent configured/not-configured decision;
5. TLS verification defaults to enabled and is not silently bypassed;
6. shared HTTP requests use bounded transport settings and explicit retry semantics;
7. every API response has a safe request ID;
8. integration errors use the approved safe envelope without secret leakage;
9. all four source package/router boundaries exist and are wired once;
10. no real source call or source-write capability is added;
11. focused and full tests pass; and
12. the final diff contains no unrelated database, deployment, Grafana, AI, Wazuh-service, or network changes.
