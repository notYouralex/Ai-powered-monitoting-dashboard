import json
from pathlib import Path

from argon2 import PasswordHasher, Type
from pydantic import SecretStr

from app.db.models import User


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = ROOT / "grafana" / "dashboards"
SETUP_FILE = ROOT / "grafana" / "README.md"
DATASOURCE_FILE = ROOT / "grafana" / "provisioning" / "datasources" / "monitoring-api.yaml"
DASHBOARD_PROVIDER_FILE = ROOT / "grafana" / "provisioning" / "dashboards" / "dashboards.yaml"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_dashboard(name: str) -> dict:
    return json.loads(read(DASHBOARD_DIR / name))


def iter_targets(dashboard: dict):
    for panel in dashboard["panels"]:
        yield from panel.get("targets", [])


def test_grafana_bearer_token_is_scoped_to_dashboard_routes(auth_env) -> None:
    token = "g" * 48
    auth_env.settings.grafana_api_token = SecretStr(token)
    headers = {"Authorization": f"Bearer {token}"}

    freshservice = auth_env.client.get("/api/dashboard/freshservice", headers=headers)
    snipe_it = auth_env.client.get("/api/dashboard/snipe-it", headers=headers)
    wazuh = auth_env.client.get("/api/dashboard/wazuh", headers=headers)
    auth_me = auth_env.client.get("/api/auth/me", headers=headers)

    assert freshservice.status_code == 200
    assert snipe_it.status_code == 200
    assert wazuh.status_code == 503
    assert wazuh.json()["error"]["code"] == "SOURCE_NOT_CONFIGURED"
    assert auth_me.status_code == 401


def test_dashboard_routes_reject_invalid_grafana_bearer_token(auth_env) -> None:
    auth_env.settings.grafana_api_token = SecretStr("g" * 48)
    headers = {"Authorization": "Bearer wrong-token"}

    assert auth_env.client.get("/api/dashboard/freshservice", headers=headers).status_code == 401
    assert auth_env.client.get("/api/dashboard/snipe-it", headers=headers).status_code == 401
    assert auth_env.client.get("/api/dashboard/wazuh", headers=headers).status_code == 401


def test_invalid_authorization_does_not_fall_back_to_signed_in_session(auth_env) -> None:
    with auth_env.session_factory() as db:
        db.add(
            User(
                username="grafana-test-user",
                password_hash=PasswordHasher(type=Type.ID).hash("correct horse"),
                is_active=True,
                is_admin=False,
            )
        )
        db.commit()

    login = auth_env.client.post(
        "/api/auth/login",
        json={"username": "grafana-test-user", "password": "correct horse"},
    )
    assert login.status_code == 200

    auth_env.settings.grafana_api_token = SecretStr("g" * 48)
    response = auth_env.client.get(
        "/api/dashboard/freshservice",
        headers={"Authorization": "Basic not-a-grafana-token"},
    )

    assert response.status_code == 401


def test_existing_grafana_setup_keeps_datasource_secret_out_of_git() -> None:
    setup = read(SETUP_FILE)

    assert "Grafana 13.1.1" in setup
    assert "Infinity 3.11.1" in setup
    assert "http://127.0.0.1:8000" in setup
    assert "GRAFANA_API_TOKEN" in setup
    assert "secure bearer token" in setup.lower()

    datasource = read(DATASOURCE_FILE)
    assert "datasources: []" in datasource
    assert "secureJsonData" not in datasource
    assert "bearerToken" not in datasource
    assert "$GRAFANA_API_TOKEN" not in datasource


def test_existing_grafana_dashboard_provisioning_is_inert() -> None:
    provider = read(DASHBOARD_PROVIDER_FILE)

    assert "providers: []" in provider
    assert "/var/lib/grafana/" not in provider


def test_wazuh_dashboard_uses_only_canonical_wazuh_api() -> None:
    dashboard = load_dashboard("wazuh.json")

    assert dashboard["uid"] == "monitoring-wazuh"
    assert dashboard["title"] == "Wazuh Security"
    assert dashboard["__inputs"] == [
        {
            "name": "DS_MONITORING_API",
            "label": "Monitoring API",
            "description": "",
            "type": "datasource",
            "pluginId": "yesoreyeram-infinity-datasource",
            "pluginName": "Infinity",
        }
    ]
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    assert set(panels) == {
        "Total Alerts",
        "Critical Alerts",
        "High Alerts",
        "Total Vulnerabilities",
        "Critical Vulnerabilities",
        "High Vulnerabilities",
        "Alert Trend",
        "MITRE Tactics",
        "Top Alerts",
        "Vulnerabilities by Severity",
        "Top Affected Agents",
        "Agent Status",
        "Recent Alerts",
    }

    for title, x in [
        ("Total Alerts", 0),
        ("Critical Alerts", 4),
        ("High Alerts", 8),
        ("Total Vulnerabilities", 12),
        ("Critical Vulnerabilities", 16),
        ("High Vulnerabilities", 20),
    ]:
        assert panels[title]["gridPos"] == {"x": x, "y": 0, "w": 4, "h": 4}

    assert panels["Alert Trend"]["gridPos"] == {"x": 0, "y": 4, "w": 8, "h": 7}
    assert panels["MITRE Tactics"]["gridPos"] == {"x": 8, "y": 4, "w": 10, "h": 7}
    assert panels["MITRE Tactics"]["type"] == "barchart"
    assert panels["Top Alerts"]["gridPos"] == {"x": 18, "y": 4, "w": 6, "h": 7}
    assert panels["Vulnerabilities by Severity"]["gridPos"] == {"x": 0, "y": 11, "w": 5, "h": 6}
    assert panels["Top Affected Agents"]["gridPos"] == {"x": 5, "y": 11, "w": 5, "h": 6}
    assert panels["Top Affected Agents"]["type"] == "piechart"
    assert panels["Agent Status"]["gridPos"] == {"x": 10, "y": 11, "w": 5, "h": 6}
    assert panels["Agent Status"]["type"] == "piechart"
    assert [column["selector"] for column in panels["Agent Status"]["targets"][0]["columns"]] == [
        "agents_active",
        "agents_disconnected",
        "agents_pending",
        "agents_never_connected",
        "agents_unknown",
    ]
    assert panels["Recent Alerts"]["gridPos"] == {"x": 15, "y": 11, "w": 9, "h": 6}

    targets = list(iter_targets(dashboard))
    assert targets
    for target in targets:
        assert target["datasource"]["uid"] == "${DS_MONITORING_API}"
        assert target["url"].startswith("/api/dashboard/wazuh")
        assert "Authorization" not in json.dumps(target)


def test_freshservice_dashboard_uses_only_canonical_freshservice_api() -> None:
    dashboard = load_dashboard("freshservice.json")

    assert dashboard["uid"] == "monitoring-freshservice"
    assert dashboard["title"] == "Freshservice Service Management"
    assert dashboard["__inputs"] == [
        {
            "name": "DS_MONITORING_API",
            "label": "Monitoring API",
            "description": "",
            "type": "datasource",
            "pluginId": "yesoreyeram-infinity-datasource",
            "pluginName": "Infinity",
        }
    ]
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    assert set(panels) == {
        "Open Tickets",
        "Pending Tickets",
        "Due Today",
        "Overdue",
        "Resolution SLA Compliance",
        "Resolved Tickets",
        "Closed Tickets",
        "Unresolved Tickets by Priority",
        "Unresolved Tickets by Status",
        "All Tickets by Status",
        "Resolution Trend",
        "Recent Tickets",
    }

    for title, x, width in [
        ("Overdue", 0, 3),
        ("Due Today", 3, 3),
        ("Open Tickets", 6, 3),
        ("Pending Tickets", 9, 3),
        ("Resolved Tickets", 12, 3),
        ("Closed Tickets", 15, 3),
        ("Resolution SLA Compliance", 18, 6),
    ]:
        assert panels[title]["gridPos"] == {"x": x, "y": 0, "w": width, "h": 4}

    assert panels["Unresolved Tickets by Priority"]["gridPos"] == {"x": 0, "y": 4, "w": 8, "h": 8}
    assert panels["Unresolved Tickets by Status"]["gridPos"] == {"x": 8, "y": 4, "w": 8, "h": 8}
    assert panels["All Tickets by Status"]["gridPos"] == {"x": 16, "y": 4, "w": 8, "h": 8}
    assert panels["Resolution Trend"]["gridPos"] == {"x": 0, "y": 12, "w": 8, "h": 8}
    assert panels["Recent Tickets"]["gridPos"] == {"x": 8, "y": 12, "w": 16, "h": 8}

    targets = list(iter_targets(dashboard))
    assert targets
    for target in targets:
        assert target["datasource"]["uid"] == "${DS_MONITORING_API}"
        assert target["url"] == "/api/dashboard/freshservice"
        assert "Authorization" not in json.dumps(target)


def test_snipe_it_dashboard_matches_clean_asset_management_layout() -> None:
    dashboard = load_dashboard("snipe-it.json")

    assert dashboard["uid"] == "monitoring-snipe-it"
    assert dashboard["title"] == "Snipe-IT Asset Management"
    assert dashboard["__inputs"] == [
        {
            "name": "DS_MONITORING_API",
            "label": "Monitoring API",
            "description": "",
            "type": "datasource",
            "pluginId": "yesoreyeram-infinity-datasource",
            "pluginName": "Infinity",
        }
    ]
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    assert set(panels) == {
        "Total Assets",
        "Deployed",
        "Available",
        "Maintenance",
        "Retired",
        "Assets by Type / Category",
        "Assets by Status",
        "Assets by Location",
        "Recent Activity",
        "Upcoming Warranty Expiry",
    }

    for title, x, width in [
        ("Total Assets", 0, 5),
        ("Deployed", 5, 5),
        ("Available", 10, 5),
        ("Maintenance", 15, 5),
        ("Retired", 20, 4),
    ]:
        assert panels[title]["gridPos"] == {"x": x, "y": 0, "w": width, "h": 4}

    assert panels["Assets by Type / Category"]["gridPos"] == {
        "x": 0,
        "y": 4,
        "w": 8,
        "h": 8,
    }
    assert panels["Assets by Status"]["gridPos"] == {"x": 8, "y": 4, "w": 8, "h": 8}
    assert panels["Assets by Location"]["gridPos"] == {"x": 16, "y": 4, "w": 8, "h": 8}
    assert panels["Recent Activity"]["gridPos"] == {"x": 0, "y": 12, "w": 14, "h": 9}
    assert panels["Upcoming Warranty Expiry"]["gridPos"] == {
        "x": 14,
        "y": 12,
        "w": 10,
        "h": 9,
    }

    summary_selectors = {
        title: panel["targets"][0]["columns"][0]["selector"]
        for title, panel in panels.items()
        if title in {"Total Assets", "Deployed", "Available", "Maintenance", "Retired"}
    }
    assert summary_selectors == {
        "Total Assets": "summary.assets_total",
        "Deployed": "summary.assets_deployed",
        "Available": "summary.assets_available",
        "Maintenance": "summary.assets_maintenance",
        "Retired": "summary.assets_retired",
    }

    targets = list(iter_targets(dashboard))
    assert targets
    for target in targets:
        assert target["datasource"]["uid"] == "${DS_MONITORING_API}"
        assert target["url_options"]["method"] == "GET"
        assert "Authorization" not in json.dumps(target)

    activity_target = panels["Recent Activity"]["targets"][0]
    assert activity_target["root_selector"] == "$.activity"
    assert activity_target["url"] == "/api/dashboard/snipe-it/recent-activity"
    assert [column["selector"] for column in activity_target["columns"]] == [
        "action",
        "asset",
        "target",
        "performed_by",
        "location",
        "occurred_at",
    ]

    warranty_target = panels["Upcoming Warranty Expiry"]["targets"][0]
    assert warranty_target["root_selector"] == "$.warranty_expiry"
    assert warranty_target["url"] == "/api/dashboard/snipe-it/warranty-expiry"

    for title, panel in panels.items():
        if title not in {"Recent Activity", "Upcoming Warranty Expiry"}:
            assert panel["targets"][0]["url"] == "/api/dashboard/snipe-it"


def test_compose_reuses_host_grafana_instead_of_defining_duplicate_service() -> None:
    compose = read(ROOT / "compose.yaml")
    api = compose.split("fastapi-api:", 1)[1].split("background-worker:", 1)[0]

    assert "\n  grafana:\n" not in compose
    assert "grafana-data:" not in compose
    assert "GRAFANA_API_TOKEN: ${GRAFANA_API_TOKEN:-}" in api
