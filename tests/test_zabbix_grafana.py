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

    assert dashboard["uid"] == "monitoring-zabbix"
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
        "text": "Monitoring API",
        "value": "monitoring-api",
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
        "Live Host Topology",
        "System Information",
        "CPU Load",
        "Memory Usage",
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

    assert panels["Live Host Topology"]["gridPos"] == {"h": 19, "w": 16, "x": 0, "y": 4}
    assert panels["System Information"]["gridPos"] == {"h": 8, "w": 8, "x": 16, "y": 4}
    assert panels["CPU Load"]["gridPos"] == {"h": 8, "w": 8, "x": 16, "y": 12}
    assert panels["Memory Usage"]["gridPos"] == {"h": 8, "w": 8, "x": 16, "y": 20}
    assert dashboard["time"] == {"from": "now-1h", "to": "now"}

    for title, metric in [("CPU Load", "cpu"), ("Memory Usage", "memory")]:
        target = panels[title]["targets"][0]
        assert target["root_selector"] == (
            "$map($.resource_live[metric='" + metric + "'], function($s) { "
            "$map($s.points, function($p) { {'time': $p.observed_at, "
            "'value': $p.used_percent, 'host': $s.host_id} }) }).*"
        )
    assert panels["Warnings"]["gridPos"] == {"h": 5, "w": 16, "x": 0, "y": 23}

    system_target = panels["System Information"]["targets"][0]
    assert system_target["root_selector"] == "$.topology_maps[0].nodes"
    assert system_target["columns"] == [
        {"selector": "title", "text": "Host", "type": "string"},
        {"selector": "status", "text": "Status", "type": "string"},
        {"selector": "active_problem_count", "text": "Problems", "type": "number"},
    ]


def test_zabbix_dashboard_live_topology_uses_network_weathermap() -> None:
    dashboard = load_dashboard()
    panel = next(
        panel
        for panel in dashboard["panels"]
        if panel["title"] == "Live Host Topology"
    )

    assert panel["type"] == "tamirsuliman-weathermap-panel"
    assert panel["pluginVersion"] == "1.6.12"
    assert "does not prove physical/interface/circuit health" in panel["description"]

    weathermap = panel["options"]["weathermap"]
    assert weathermap["version"] == 14
    assert weathermap["id"] == "zabbix-hijo-network-map"
    assert len(weathermap["nodes"]) == 25
    assert len(weathermap["links"]) == 26

    nodes = {node["id"]: node for node in weathermap["nodes"]}
    assert nodes["4"]["position"] == [228, 127]
    assert nodes["5"]["position"] == [277, 363]
    assert nodes["21"]["position"] == [719, 639]
    assert nodes["26"]["position"] == [1137, 416]
    assert nodes["4"]["nodeIcon"]["name"] == "networking/firewall"
    assert nodes["5"]["nodeIcon"]["name"] == "networking/switch"
    assert nodes["6"]["nodeIcon"]["name"] == "networking/server"
    assert nodes["9"]["nodeIcon"]["name"] == "networking/radio-tower"
    assert nodes["7"]["nodeIcon"]["name"] == "cisco/system-controller"
    assert all(
        node["nodeIcon"]["src"].startswith(
            "public/plugins/tamirsuliman-weathermap-panel/icons/"
        )
        for node in nodes.values()
    )

    expected_status_colors = {
        0: "#d44a3a",
        1: "#6e6e6e",
        2: "#8e8e8e",
        3: "#f2cc0c",
        4: "#ff9830",
        5: "#299c46",
    }
    for node in nodes.values():
        assert node["statusQuery"] == f"node_{node['id']}_status"
        assert node["tooltipMetrics"] == [
            {
                "label": "Active problems",
                "query": f"node_{node['id']}_problems",
                "units": "none",
            }
        ]
        assert node["nodeStatusColorTarget"] == "both"
        assert {
            mapping["value"]: mapping["color"]
            for mapping in node["statusValueMappings"]
        } == expected_status_colors

    settings = weathermap["settings"]
    assert settings["panel"]["panelSize"] == {"width": 1250, "height": 1050}
    assert settings["panel"]["viewZoomPan"] is True
    assert settings["link"]["stroke"]["color"] == "#299c46"
    assert settings["link"]["flowAnimation"]["enabled"] is False
    assert settings["animation"]["enabled"] is False
    assert settings["statusLegend"]["enabled"] is True
    legend_labels = {
        item["label"] for item in settings["statusLegend"]["items"]
    }
    assert "PROBLEM / active host problem" in legend_labels
    assert any("not physical-link telemetry" in label for label in legend_labels)

    links = weathermap["links"]
    assert all(link["statusDownColor"] == "#d44a3a" for link in links)
    assert all(link["statusBlink"] is True for link in links)
    assert all(link["animation"] == "disabled" for link in links)
    assert all(
        "query" not in link["sides"][side]
        for link in links
        for side in ("A", "Z")
    )
    assert [link["nodes"] for link in links[:4]] == [
        [{"id": "4"}, {"id": "2"}],
        [{"id": "3"}, {"id": "4"}],
        [{"id": "5"}, {"id": "4"}],
        [{"id": "4"}, {"id": "6"}],
    ]

    active_targets = [target for target in panel["targets"] if not target.get("hide")]
    assert [target["refId"] for target in active_targets] == ["status"]
    status_target = active_targets[0]
    assert status_target["url"] == "/api/dashboard/zabbix"
    assert status_target["format"] == "table"
    assert status_target["parser"] == "backend"
    assert "topology_maps[map_id='3'][0]" in status_target["root_selector"]
    assert "active_problem_count" in status_target["root_selector"]
    assert "unavailable" in status_target["root_selector"]

    fields = {column["text"] for column in status_target["columns"]}
    assert {f"node_{node_id}_status" for node_id in nodes} <= fields
    assert {f"node_{node_id}_problems" for node_id in nodes} <= fields
    assert {link["statusQuery"] for link in links} <= fields


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


def test_zabbix_dashboard_exposes_actionable_warnings_without_health_panel() -> None:
    dashboard = load_dashboard()
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    assert "Integration Health" not in panels
    warning_target = panels["Warnings"]["targets"][0]
    assert warning_target["root_selector"] == (
        "$map($.warnings, function($w) { {'warning': $w} })"
    )
    assert warning_target["columns"] == [
        {"selector": "warning", "text": "Warning", "type": "string"}
    ]


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
