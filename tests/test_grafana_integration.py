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
    titles = {panel["title"] for panel in dashboard["panels"]}
    assert {
        "Critical Alerts",
        "High Alerts",
        "Active Agents",
        "Disconnected Agents",
        "Critical Vulnerabilities",
        "Alert Trend",
        "Top Affected Agents",
        "Recent Alerts",
    }.issubset(titles)

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
    titles = {panel["title"] for panel in dashboard["panels"]}
    assert {
        "Open Tickets",
        "Pending Tickets",
        "Due Today",
        "Overdue",
        "Resolved - Last 6 Months",
        "Closed - Last 6 Months",
        "Unresolved Tickets by Priority",
        "Unresolved Tickets by Status",
        "All Tickets by Status - Last 6 Months",
        "Resolution Trend - Last 6 Months",
        "Recent Tickets",
    }.issubset(titles)

    targets = list(iter_targets(dashboard))
    assert targets
    for target in targets:
        assert target["datasource"]["uid"] == "${DS_MONITORING_API}"
        assert target["url"] == "/api/dashboard/freshservice"
        assert "Authorization" not in json.dumps(target)


def test_snipe_it_dashboard_uses_only_canonical_snipe_it_api() -> None:
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
    titles = {panel["title"] for panel in dashboard["panels"]}
    assert {
        "Total Assets",
        "Assigned Assets",
        "Unassigned Assets",
        "Missing Serial",
        "Missing Asset Tag",
        "Warranty Expired",
        "Warranty Expiring Soon",
        "Integration Health",
        "Stale Data",
        "Observed At",
        "Last Successful Sync",
        "Assets by Status",
        "Assets by Category",
        "Assets by Location",
        "Warnings",
    }.issubset(titles)

    targets = list(iter_targets(dashboard))
    assert targets
    for target in targets:
        assert target["datasource"]["uid"] == "${DS_MONITORING_API}"
        assert target["url"] == "/api/dashboard/snipe-it"
        assert target["url_options"]["method"] == "GET"
        assert "Authorization" not in json.dumps(target)


def test_compose_reuses_host_grafana_instead_of_defining_duplicate_service() -> None:
    compose = read(ROOT / "compose.yaml")
    api = compose.split("fastapi-api:", 1)[1].split("background-worker:", 1)[0]

    assert "\n  grafana:\n" not in compose
    assert "grafana-data:" not in compose
    assert "GRAFANA_API_TOKEN: ${GRAFANA_API_TOKEN:-}" in api
