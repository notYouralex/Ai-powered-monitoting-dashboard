import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "grafana" / "dashboards" / "zabbix-infrastructure.json"


def load_dashboard() -> dict:
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


def test_zabbix_dashboard_matches_finalized_infrastructure_layout() -> None:
    dashboard = load_dashboard()
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    assert "Integration Health" not in panels
    assert set(panels) == {
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
        "Network Latency",
        "Network Bandwidth",
    }

    topology = panels["Live Host Topology"]
    assert topology["type"] == "tamirsuliman-weathermap-panel"
    assert topology["pluginVersion"] == "1.6.12"
    assert topology["gridPos"] == {"x": 0, "y": 4, "w": 16, "h": 19}

    weathermap = topology["options"]["weathermap"]
    assert weathermap["version"] == 14
    assert len(weathermap["nodes"]) == 25
    assert len(weathermap["links"]) == 26
    assert weathermap["settings"]["link"]["flowAnimation"]["enabled"] is False
    assert weathermap["settings"]["statusLegend"]["enabled"] is True

    status = next(
        target
        for target in topology["targets"]
        if target["refId"] == "status" and not target.get("hide")
    )
    assert status["url"] == "/api/dashboard/zabbix"
    assert status["format"] == "table"
    assert "topology_maps[map_id='3'][0]" in status["root_selector"]
    assert "active_problem_count" in status["root_selector"]
    assert "unavailable" in status["root_selector"]
    assert all(link["statusBlink"] is True for link in weathermap["links"])
    assert all(
        "query" not in link["sides"][side]
        for link in weathermap["links"]
        for side in ("A", "Z")
    )

    warnings = panels["Warnings"]
    assert warnings["gridPos"] == {"x": 0, "y": 23, "w": 16, "h": 5}
    assert panels["Network Latency"]["gridPos"] == {"x": 0, "y": 28, "w": 12, "h": 8}
    assert panels["Network Bandwidth"]["gridPos"] == {"x": 12, "y": 28, "w": 12, "h": 8}
    assert warnings["targets"][0]["root_selector"] == (
        "$map($.warnings, function($w) { {'warning': $w} })"
    )

    assert dashboard["refresh"] == "30s"


def test_zabbix_dashboard_uses_only_canonical_fastapi_endpoint() -> None:
    dashboard = load_dashboard()

    for panel in dashboard["panels"]:
        for target in panel.get("targets", []):
            assert target["datasource"]["uid"] == "${zabbix_ds}"
            assert target["url"] == "/api/dashboard/zabbix"
            assert "Authorization" not in json.dumps(target)
