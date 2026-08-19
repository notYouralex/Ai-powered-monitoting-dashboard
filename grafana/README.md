# Existing Grafana integration

This project reuses the existing host-installed Grafana instead of starting a second Grafana container.

## Verified local baseline

The current host uses Grafana 13.1.1 on HTTPS port 3000 and already has Infinity 3.11.1 installed. The FastAPI service is exposed only on the local host at `http://127.0.0.1:8000`.

## Monitoring API datasource

Create one Infinity datasource in the existing Grafana instance with these settings:

- Name: `Monitoring API`
- Base URL: `http://127.0.0.1:8000`
- Authentication: Bearer token
- Allowed host: `http://127.0.0.1:8000`

Use the same `GRAFANA_API_TOKEN` value configured for the FastAPI container. Enter it only in Grafana's secure bearer token field. Do not place the real token in dashboard JSON, provisioning YAML, documentation, or Git.

The repository intentionally does not provision the datasource secret. `grafana/provisioning/datasources/monitoring-api.yaml` is an inert placeholder so copying the repository does not overwrite securely stored datasource credentials.

## Dashboards

The source-controlled dashboard templates are:

- `grafana/dashboards/wazuh.json`
- `grafana/dashboards/freshservice.json`
- `grafana/dashboards/snipe-it.json`
- `grafana/dashboards/zabbix-infrastructure.json`
- `grafana/dashboards/executive.json`

They query only the canonical FastAPI dashboard endpoints. Wazuh, Freshservice, Snipe-IT, and the Executive dashboard use a Grafana datasource input placeholder; the Zabbix reference dashboard uses an Infinity datasource variable. Point every dashboard at the same securely configured `Monitoring API` datasource when imported.

The Executive dashboard queries only `/api/dashboard/executive`. The backend derives render-ready headline metrics, health/category/status distributions, and attention counts from the four normalized source summaries; Grafana only selects those returned rows and fields. `Overall Health` is the percentage of canonical integrations currently reporting healthy. The dashboard does not invent SLA, trend, recent-alert, unavailable-host, or AI fields that are not present in the merged backend contract.

Freshservice historical panels use a six-calendar-month ticket creation-date scope in the `Asia/Manila` timezone to match the Freshservice reporting view. This applies to Pending, Resolved, Closed, all-ticket status distribution, category distribution, and resolution trend data. Current operational metrics such as Open, Due Today, Overdue, Escalated, and unresolved distributions remain current-state counts even when an older ticket is still actionable.

Import each dashboard through the existing Grafana UI:

1. Open **Dashboards**.
2. Choose **New > Import**.
3. Upload the dashboard JSON file.
4. When Grafana asks for the `Monitoring API` datasource, select the Infinity datasource created above.
5. Import the dashboard.

This UI-import approach keeps the bearer token in Grafana's secure datasource configuration and avoids coupling the repository to the locally generated datasource UID. The dashboard provisioning file is intentionally inert for this deployment.

## Runtime sequence

1. Rebuild/recreate the FastAPI API container so it loads the new `GRAFANA_API_TOKEN` authentication support.
2. Confirm bearer-token access to `/api/dashboard/wazuh`, `/api/dashboard/freshservice`, `/api/dashboard/snipe-it`, `/api/dashboard/zabbix`, and `/api/dashboard/executive`.
3. Configure the Infinity datasource in the existing Grafana UI using the secure bearer token field.
4. Import the Wazuh, Freshservice, Snipe-IT, Zabbix, and Executive dashboard JSON files and point them at the Monitoring API datasource.
5. Validate panel rendering and data freshness in Grafana.
