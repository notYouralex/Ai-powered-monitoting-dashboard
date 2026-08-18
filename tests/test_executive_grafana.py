import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_FILE = ROOT / "grafana" / "dashboards" / "executive.json"
EXECUTIVE_URL = "/api/dashboard/executive?from=${__from:date:iso}&to=${__to:date:iso}"


def load_dashboard() -> dict:
    return json.loads(DASHBOARD_FILE.read_text(encoding="utf-8"))


def test_executive_dashboard_uses_only_shared_executive_api() -> None:
    dashboard = load_dashboard()

    assert dashboard["uid"] == "monitoring-executive"
    assert dashboard["title"] == "Executive Overview"
    assert dashboard["refresh"] == "1m"
    assert dashboard["time"] == {"from": "now-24h", "to": "now"}
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

    targets = [target for panel in dashboard["panels"] for target in panel.get("targets", [])]
    assert targets
    for target in targets:
        assert target["datasource"]["uid"] == "${DS_MONITORING_API}"
        assert target["url"] == EXECUTIVE_URL
        assert target["url_options"]["method"] == "GET"
        assert "Authorization" not in json.dumps(target)
        assert "/api/dashboard/wazuh" not in target["url"]
        assert "/api/dashboard/zabbix" not in target["url"]
        assert "/api/dashboard/snipe-it" not in target["url"]
        assert "/api/dashboard/freshservice" not in target["url"]


def test_executive_dashboard_surfaces_available_executive_contract_fields() -> None:
    dashboard = load_dashboard()
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    expected_titles = {
        "Critical Security Alerts",
        "High Security Alerts",
        "Disaster Problems",
        "Unavailable Interfaces",
        "High-Priority Open Tickets",
        "Expired Warranties",
        "Wazuh Health",
        "Zabbix Health",
        "Snipe-IT Health",
        "Freshservice Health",
        "Observed At",
        "Source Health & Freshness",
        "Source Warnings",
    }
    assert expected_titles.issubset(panels)

    expected_metrics = {
        "Critical Security Alerts": ("wazuh", "alerts_critical"),
        "High Security Alerts": ("wazuh", "alerts_high"),
        "Disaster Problems": ("zabbix", "problems_disaster"),
        "Unavailable Interfaces": ("zabbix", "interfaces_unavailable"),
        "High-Priority Open Tickets": ("freshservice", "high_priority_open"),
        "Expired Warranties": ("snipe_it", "warranty_expired"),
    }
    for title, (source, metric) in expected_metrics.items():
        target = panels[title]["targets"][0]
        assert source in target["root_selector"]
        assert target["columns"] == [{"selector": metric, "text": metric, "type": "number"}]

    for title, source in {
        "Wazuh Health": "wazuh",
        "Zabbix Health": "zabbix",
        "Snipe-IT Health": "snipe_it",
        "Freshservice Health": "freshservice",
    }.items():
        target = panels[title]["targets"][0]
        assert source in target["root_selector"]
        assert target["columns"] == [{"selector": "status", "text": "status", "type": "string"}]

    freshness_target = panels["Source Health & Freshness"]["targets"][0]
    assert "$.sources" in freshness_target["root_selector"]
    assert {column["selector"] for column in freshness_target["columns"]} == {
        "source",
        "status",
        "is_stale",
        "last_success_at",
    }

    warnings_target = panels["Source Warnings"]["targets"][0]
    assert "$.sources" in warnings_target["root_selector"]
    assert {column["selector"] for column in warnings_target["columns"]} == {"source", "warnings"}


def test_executive_dashboard_does_not_query_unmerged_backend_fields() -> None:
    dashboard = load_dashboard()
    query_text = json.dumps(
        [target for panel in dashboard["panels"] for target in panel.get("targets", [])]
    ).lower()

    assert "overall_status" not in query_text
    assert "ai_summary" not in query_text
    assert "top_risks" not in query_text
    assert "operational_trend" not in query_text
    assert "hosts_unavailable" not in query_text
