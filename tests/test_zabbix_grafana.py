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


def test_zabbix_dashboard_uses_global_view_layout() -> None:
    dashboard = load_dashboard()
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    expected_titles = {
        "Hosts",
        "Problems",
        "Unreachable",
        "Avg CPU Usage",
        "Critical Problems",
        "Availability Map",
        "System Information",
        "CPU Load",
        "Memory Usage",
        "Integration Health",
        "Warnings",
    }
    assert set(panels) == expected_titles

    for title, x, width in [
        ("Hosts", 0, 5),
        ("Problems", 5, 5),
        ("Unreachable", 10, 5),
        ("Avg CPU Usage", 15, 5),
        ("Critical Problems", 20, 4),
    ]:
        panel = panels[title]
        assert panel["type"] == "stat"
        assert panel["gridPos"] == {"h": 4, "w": width, "x": x, "y": 0}

    expected_summary_metrics = {
        "Hosts": "hosts_enabled",
        "Problems": "problems_total",
        "Unreachable": "interfaces_unavailable",
        "Critical Problems": "problems_disaster",
    }
    for title, selector in expected_summary_metrics.items():
        target = panels[title]["targets"][0]
        assert target["root_selector"] == "$append([], $.summary)"
        assert target["columns"] == [{"selector": selector, "text": selector, "type": "number"}]

    cpu_stat = panels["Avg CPU Usage"]
    assert cpu_stat["fieldConfig"]["defaults"]["unit"] == "percent"
    assert cpu_stat["options"]["reduceOptions"]["calcs"] == ["mean"]
    assert cpu_stat["targets"][0]["root_selector"] == "$.resource_pressure"
    assert cpu_stat["targets"][0]["columns"] == [
        {"selector": "cpu_used_percent", "text": "cpu_used_percent", "type": "number"}
    ]

    assert panels["Availability Map"]["gridPos"] == {"h": 10, "w": 13, "x": 0, "y": 4}
    assert panels["System Information"]["gridPos"] == {"h": 10, "w": 11, "x": 13, "y": 4}
    assert panels["CPU Load"]["gridPos"] == {"h": 8, "w": 12, "x": 0, "y": 14}
    assert panels["Memory Usage"]["gridPos"] == {"h": 8, "w": 12, "x": 12, "y": 14}
    assert dashboard["time"] == {"from": "now-1h", "to": "now"}

    for title, metric in [("CPU Load", "cpu"), ("Memory Usage", "memory")]:
        target = panels[title]["targets"][0]
        assert target["root_selector"] == (
            "$map($.resource_live[metric='" + metric + "'], function($s) { "
            "$map($s.points, function($p) { {'time': $p.observed_at, "
            "'value': $p.used_percent, 'host': $s.host_id} }) }).*"
        )
    assert panels["Integration Health"]["gridPos"] == {"h": 4, "w": 6, "x": 0, "y": 22}
    assert panels["Warnings"]["gridPos"] == {"h": 4, "w": 18, "x": 6, "y": 22}

    system_target = panels["System Information"]["targets"][0]
    assert system_target["root_selector"] == "$.topology_maps[0].nodes"
    assert system_target["columns"] == [
        {"selector": "title", "text": "Host", "type": "string"},
        {"selector": "status", "text": "Status", "type": "string"},
        {"selector": "active_problem_count", "text": "Problems", "type": "number"},
    ]


def test_zabbix_dashboard_availability_map_uses_node_graph_frames() -> None:
    dashboard = load_dashboard()
    panel = next(panel for panel in dashboard["panels"] if panel["title"] == "Availability Map")

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


def test_zabbix_dashboard_exposes_health_and_stale_state() -> None:
    dashboard = load_dashboard()
    health_panel = next(panel for panel in dashboard["panels"] if panel["title"] == "Integration Health")
    selectors = {
        column["selector"]
        for target in health_panel["targets"]
        for column in target.get("columns", [])
    }

    assert selectors == {"health.status", "is_stale"}


def test_zabbix_dashboard_file_provisioning_is_inert_for_host_grafana() -> None:
    provider = PROVIDER_PATH.read_text(encoding="utf-8")

    assert "apiVersion: 1" in provider
    assert "providers: []" in provider
    assert "/var/lib/grafana/" not in provider
    assert "allowUiUpdates" not in provider


def test_zabbix_specific_datasource_provisioning_is_inert_and_secret_free() -> None:
    datasource = DATASOURCE_PATH.read_text(encoding="utf-8")

    assert "apiVersion: 1" in datasource
    assert "datasources: []" in datasource
    assert "uid:" not in datasource
    assert "secureJsonData" not in datasource
    assert "bearerToken" not in datasource
    assert "$GRAFANA_API_TOKEN" not in datasource
