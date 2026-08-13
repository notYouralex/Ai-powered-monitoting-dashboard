# Dashboard Flexibility Guidelines

## Purpose

The platform provides project-maintained default Grafana dashboards while allowing authorized users to customize how normalized monitoring data is presented.

The core rule is:

> FastAPI defines what a metric means. Grafana defines how that metric is displayed.

This keeps metric definitions consistent across source dashboards, the Executive dashboard, Grafana views, and future AI summaries while still allowing teams to adapt dashboard presentation to their needs.

## Canonical Metric Ownership

FastAPI and the source integration services own canonical metric definitions and normalized datasets.

Business rules must be implemented in the backend rather than independently inside Grafana panels. A canonical metric must keep the same meaning wherever it is consumed.

Grafana must not silently redefine, reinterpret, or duplicate backend business logic.

## Grafana Presentation Flexibility

Grafana is responsible for presentation of canonical backend data.

Authorized users may customize presentation by:

- rearranging panels;
- resizing panels;
- hiding panels they do not need;
- changing visualization types when the underlying dataset supports them;
- changing panel titles and descriptions;
- changing thresholds, units, legends, and display options;
- adding supported dashboard variables and filters;
- changing dashboard layout for a team or role;
- creating personal or team-specific dashboard copies.

These presentation changes must not change the meaning of canonical backend metrics.

## Default Dashboard Policy

The project will provide default Grafana dashboards so users have a useful baseline without building dashboards from scratch.

The project-maintained default dashboard is the reference view and should remain stable and recoverable through provisioning or source-controlled dashboard definitions.

When practical, users should customize a saved copy instead of modifying the canonical provisioned dashboard directly.

This provides both:

- a consistent project-maintained default; and
- flexible user or team presentation.

## Allowed Customization Boundary

Users may change **how** data is displayed, but they should not change **what the data means**.

Examples of allowed customization include:

- displaying the same metric as a Stat, gauge, bar chart, table, or other suitable visualization;
- moving a metric to a different dashboard row;
- hiding a metric that is not relevant to a role;
- changing display thresholds;
- adjusting panel descriptions or labels;
- using supported filters or variables;
- creating alternate dashboard layouts for different teams.

Examples of changes that belong in the backend instead of Grafana include:

- redefining which source records count toward a canonical metric;
- combining source statuses into a new business meaning without a backend contract;
- changing the definition of severity, priority, availability, overdue state, or another canonical concept only in one dashboard;
- implementing duplicate normalization logic in Grafana queries;
- creating a dashboard-specific definition that conflicts with Executive or AI summaries.

## Consistency Requirement

The same canonical metric should produce the same business meaning across:

- source-specific dashboards;
- the Executive dashboard;
- customized Grafana views;
- API consumers;
- future AI summaries and explanations.

Different dashboards may visualize or emphasize the metric differently, but they should not disagree because of different business-rule implementations.

## Dashboard Copies and User Changes

The canonical default dashboard should remain the project reference.

User or team customization should preferably be stored as separate dashboard copies or separately managed dashboard definitions. This makes it possible to:

- update the project default safely;
- preserve user-specific layouts;
- compare customized views with the reference dashboard;
- restore the default without losing user work.

Grafana permissions should determine who can view, edit, or create dashboard copies.

## Architecture Boundary

```text
Source integrations
       |
       v
Canonical FastAPI metrics and normalized datasets
       |
       +----------------------+----------------------+
       |                      |                      |
       v                      v                      v
Default Grafana dashboard  Team dashboard copy   User dashboard copy
       |                      |                      |
       +----------------------+----------------------+
                              |
                              v
                 Same canonical metric meaning
```

## Design Principle

Dashboard flexibility should increase presentation choice without reducing data consistency.

The project therefore follows this rule:

**Backend = canonical meaning. Grafana = customizable presentation.**
