import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = ROOT / "grafana/dashboards/zabbix-infrastructure.json"
PROVIDER_PATH = ROOT / "grafana/provisioning/dashboards/zabbix.yaml"
DATASOURCE_PATH = ROOT / "grafana/provisioning/datasources/zabbix-fastapi.yaml"


def load_dashboard() -> dict:
    return json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))


def test_zabbix_dashboard_is_source_controlled_and_refreshes_frequently() -> None:
    dashboard = load_dashboard()

    assert dashboard["uid"] == "zabbix-infrastructure"
    assert dashboard["title"] == "Zabbix Infrastructure"
    assert dashboard["refresh"] == "30s"
    assert dashboard["timezone"] == "browser"
    assert {"zabbix", "infrastructure"}.issubset(set(dashboard["tags"]))


def test_zabbix_dashboard_uses_an_infinity_datasource_variable() -> None:
    dashboard = load_dashboard()
    variables = {item["name"]: item for item in dashboard["templating"]["list"]}

    datasource = variables["zabbix_ds"]
    assert datasource["type"] == "datasource"
    assert datasource["query"] == "yesoreyeram-infinity-datasource"
    assert datasource["current"] == {
        "selected": True,
        "text": "Zabbix FastAPI",
        "value": "zabbix-fastapi",
    }

    for panel in dashboard["panels"]:
        for target in panel.get("targets", []):
            assert target["datasource"] == {
                "type": "yesoreyeram-infinity-datasource",
                "uid": "${zabbix_ds}",
            }
            assert target["source"] == "url"
            assert target["type"] == "json"
            assert target["url"] == "/api/dashboard/zabbix"
            assert target["url_options"]["method"] == "GET"


def test_zabbix_dashboard_covers_the_approved_infrastructure_views() -> None:
    dashboard = load_dashboard()
    panel_titles = {panel["title"] for panel in dashboard["panels"]}

    assert {
        "Integration Health",
        "Host Availability",
        "Interface Availability",
        "Active Problems",
        "Active Problems by Severity",
        "Resource Pressure",
        "Top Affected Hosts",
        "Network Topology",
        "CPU Trend",
        "Memory Trend",
        "Disk Trend",
        "Warnings",
        "AI Infrastructure Summary",
    }.issubset(panel_titles)


def test_zabbix_dashboard_network_topology_uses_node_graph_frames() -> None:
    dashboard = load_dashboard()
    panel = next(panel for panel in dashboard["panels"] if panel["title"] == "Network Topology")

    assert panel["type"] == "nodeGraph"
    targets = {target["refId"]: target for target in panel["targets"]}
    assert targets["nodes"]["format"] == "node-graph-nodes"
    assert targets["nodes"]["root_selector"] == "$.topology_maps[0].nodes"
    assert targets["edges"]["format"] == "node-graph-edges"
    assert targets["edges"]["root_selector"] == "$.topology_maps[0].edges"


def test_zabbix_dashboard_uses_only_normalized_fastapi_contract() -> None:
    serialized = json.dumps(load_dashboard(), sort_keys=True)

    assert "/api/dashboard/zabbix" in serialized
    assert "api_jsonrpc.php" not in serialized
    assert "host.get" not in serialized
    assert "problem.get" not in serialized
    assert "item.get" not in serialized
    assert "trend.get" not in serialized
    assert '"method": "POST"' not in serialized
    assert '"method": "PUT"' not in serialized
    assert '"method": "PATCH"' not in serialized
    assert '"method": "DELETE"' not in serialized


def test_zabbix_dashboard_exposes_freshness_and_stale_state() -> None:
    dashboard = load_dashboard()
    health_panel = next(panel for panel in dashboard["panels"] if panel["title"] == "Integration Health")
    selectors = {
        column["selector"]
        for target in health_panel["targets"]
        for column in target.get("columns", [])
    }

    assert {"health.status", "is_stale", "health.last_success_at", "observed_at"}.issubset(selectors)


def test_zabbix_dashboard_file_provisioning_is_stable_and_read_only() -> None:
    provider = PROVIDER_PATH.read_text(encoding="utf-8")

    assert "apiVersion: 1" in provider
    assert "name: Zabbix Infrastructure" in provider
    assert "folder: Infrastructure" in provider
    assert "type: file" in provider
    assert "allowUiUpdates: false" in provider
    assert "updateIntervalSeconds: 30" in provider
    assert "path: /var/lib/grafana/dashboards/zabbix" in provider


def test_zabbix_fastapi_datasource_uses_environment_backed_bearer_auth() -> None:
    datasource = DATASOURCE_PATH.read_text(encoding="utf-8")

    assert "name: Zabbix FastAPI" in datasource
    assert "uid: zabbix-fastapi" in datasource
    assert "type: yesoreyeram-infinity-datasource" in datasource
    assert "url: http://127.0.0.1:$APP_PORT" in datasource
    assert "auth_method: bearerToken" in datasource
    assert "allowDangerousHTTPMethods: false" in datasource
    assert "bearerToken: $GRAFANA_SERVICE_TOKEN" in datasource
    assert "Bearer " not in datasource
    assert "replace-" not in datasource
