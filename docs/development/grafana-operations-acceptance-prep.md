# Grafana Operations Acceptance and Handover Preparation

## Status

**Preparation only.** This checklist prepares Milestone 7B while Milestones 5B and 6 are still pending. It must not be treated as evidence that final Grafana, AI, HTTPS, or handover validation has passed.

Final 7B acceptance starts only after the functional milestones are complete and the final deployment model is available.

## Purpose

Use this checklist during final Grafana and operations acceptance to verify that the project-maintained dashboards consume canonical FastAPI data, use the existing host-installed Grafana deployment safely, and can be handed to an operator without exposing secrets or depending on undocumented local state.

The project rule remains:

> FastAPI defines what a metric means. Grafana defines how that metric is displayed.

## Prerequisites Before Final 7B Validation

- [ ] Milestone 5A local AI backend/orchestration is merged and its API contract is stable.
- [ ] Milestone 5B Executive AI visualization is merged.
- [ ] Milestone 6 internal HTTPS/reverse-proxy deployment model is merged.
- [ ] Final dashboard JSON files are present on the branch being accepted.
- [ ] Final deployment/operator documentation reflects the merged runtime configuration.
- [ ] Any runtime or service changes required for validation have separate explicit user permission.

## Grafana Deployment Baseline

Confirm the final environment still follows the project deployment model.

- [ ] Existing host-installed Grafana is reused; no duplicate Grafana container was introduced.
- [ ] Infinity datasource is available for the `Monitoring API` datasource.
- [ ] Datasource credentials remain in Grafana secure configuration and are not stored in Git.
- [ ] Repository provisioning files remain safe for the approved deployment model.
- [ ] Dashboard datasource references do not depend on hard-coded environment-specific UIDs when the existing input/variable pattern can be used.

## Monitoring API Datasource Acceptance

Validate the configured `Monitoring API` datasource without exposing its bearer token.

- [ ] Datasource points to the approved internal FastAPI endpoint for the final deployment model.
- [ ] Bearer-token authentication succeeds.
- [ ] Allowed-host configuration is restricted to the approved internal FastAPI endpoint.
- [ ] Datasource health check succeeds.
- [ ] No bearer token, authorization header value, password, API key, or other secret appears in dashboard JSON, provisioning YAML, logs captured for handover, or documentation.

## Source Dashboard Acceptance

Validate the project-maintained source dashboards against their canonical FastAPI endpoints.

- [ ] Wazuh dashboard loads and renders expected panels.
- [ ] Freshservice dashboard loads and renders expected panels.
- [ ] Zabbix Infrastructure dashboard loads and renders expected panels.
- [ ] Snipe-IT dashboard loads and renders expected panels.
- [ ] Dashboard time ranges and filters behave as documented.
- [ ] Empty datasets do not produce misleading values.
- [ ] Unavailable or degraded source behavior is understandable to the operator.
- [ ] Source dashboards do not reproduce backend normalization or business rules in Grafana queries.

## Executive Dashboard Acceptance

Validate `grafana/dashboards/executive.json` as the shared Executive view.

- [ ] Dashboard imports or loads successfully.
- [ ] Existing headline, distribution, source-health, and attention panels render from canonical Executive API output.
- [ ] Dashboard uses the shared `Monitoring API` datasource.
- [ ] Dashboard time-range parameters are passed to the backend instead of redefining backend time logic.
- [ ] One unavailable, stale, or not-configured source does not make unrelated Executive panels unusable.
- [ ] Grafana does not query raw Wazuh, Zabbix, Snipe-IT, or Freshservice APIs from the Executive dashboard.
- [ ] Grafana does not implement conflicting health, severity, ticket, asset, or alert definitions.

## Executive AI Panel Acceptance

These checks become active only after Milestone 5B is merged.

- [ ] `AI Insight (Summary)` is present in the Executive dashboard.
- [ ] The panel uses the stable merged Executive AI endpoint from Milestone 5A.
- [ ] The panel uses `${DS_MONITORING_API}` rather than a direct model/runtime connection.
- [ ] The panel passes the selected Grafana `from` and `to` range to the backend when required by the merged contract.
- [ ] The panel displays only bounded backend output intended for Grafana presentation.
- [ ] AI summary/confidence/warning information is understandable when returned by the backend.
- [ ] AI-disabled, model-unavailable, timeout, or other safe backend error states do not expose runtime details or secrets in Grafana.
- [ ] Dashboard JSON contains no Ollama URL, `/api/generate` call, model credential, or direct model orchestration logic.
- [ ] Source-specific AI routes are not substituted for the Executive AI contract unless separately approved.

## Dashboard JSON and Repository Checks

- [ ] Every project-maintained dashboard JSON file parses successfully.
- [ ] Executive AI Grafana focused tests pass after their preparation-only skip is removed.
- [ ] Existing Grafana-focused tests pass.
- [ ] Full available project test suite passes before release handoff.
- [ ] `git diff --check` passes.
- [ ] Final diff contains only intended milestone changes.
- [ ] No secrets or sensitive runtime values are tracked.

## Operator Handover Procedure

The final handover document should tell an operator how to perform these actions without modifying backend business logic.

- [ ] Identify the existing Grafana instance used by the project.
- [ ] Verify the `Monitoring API` datasource and its health without revealing the bearer token.
- [ ] Import or restore each project-maintained dashboard using its source-controlled JSON definition.
- [ ] Select the securely configured `Monitoring API` datasource during dashboard import when Grafana requests it.
- [ ] Verify expected panel rendering and data freshness.
- [ ] Distinguish a source integration problem from a Grafana visualization problem.
- [ ] Restore the project-maintained default dashboard from source control if a customized copy becomes unusable.
- [ ] Preserve user/team dashboard copies separately from the canonical project-maintained dashboard.
- [ ] Record the final internal HTTPS/reverse-proxy access path after Milestone 6 is merged.
- [ ] Record approved service/configuration validation commands without embedding secrets.

## Troubleshooting Handover Notes

The final operator documentation should provide a bounded troubleshooting sequence:

1. Confirm Grafana itself is reachable through the approved internal access path.
2. Confirm the `Monitoring API` datasource health status.
3. Confirm the relevant canonical FastAPI endpoint is reachable with approved authentication.
4. Determine whether the backend reports healthy, degraded, unavailable, stale, or not-configured source state.
5. Check whether the issue affects one dashboard/source or all dashboards.
6. Compare the affected dashboard with its source-controlled reference JSON.
7. Escalate backend/source integration failures to the appropriate owner instead of changing Grafana business logic.

Do not instruct operators to disable authentication, TLS verification, monitoring controls, or other security protections as a troubleshooting shortcut.

## Evidence to Capture During Final Acceptance

Record final results without recording secrets.

| Check | Result | Evidence/Notes |
|---|---|---|
| Monitoring API datasource health | Not run | Final runtime validation pending |
| Source dashboard rendering | Not run | Final runtime validation pending |
| Executive dashboard rendering | Not run | Final runtime validation pending |
| Executive AI panel rendering | Blocked | Requires merged 5A and 5B |
| Internal HTTPS access | Blocked | Requires merged Milestone 6 |
| Grafana-focused tests | Not run | Run during final 7B validation |
| Full available test suite | Not run | Required before release handoff |
| Dashboard JSON validation | Not run | Run against final dashboard files |
| Secret review | Not run | Run against final diff/configuration |
| Operator handover walkthrough | Not run | Perform after deployment model is final |

## Completion Gate

Milestone 7B is ready for handoff only when the applicable checklist items above have evidence, the final operator documentation matches the deployed architecture, and no unverified runtime behavior is reported as validated.

If runtime validation cannot be performed, report exactly:

**"The change has been prepared, but runtime validation has not been performed."**
