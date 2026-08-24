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


def test_executive_dashboard_matches_approved_summary_layout() -> None:
    dashboard = load_dashboard()
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    assert set(panels) == {
        "Overall Health",
        "Security Alerts",
        "Open Tickets",
        "Overdue Tickets",
        "SLA Compliance",
        "Assets",
        "High-Severity Issues by Domain",
        "Tickets by Status",
        "Source Health & Freshness",
        "Attention Required",
    }
    assert "AI Insight (Summary)" not in panels
    assert "Observed At" not in panels

    expected_layout = {
        "Overall Health": {"x": 0, "y": 0, "w": 4, "h": 4},
        "Security Alerts": {"x": 4, "y": 0, "w": 4, "h": 4},
        "Open Tickets": {"x": 8, "y": 0, "w": 4, "h": 4},
        "Overdue Tickets": {"x": 12, "y": 0, "w": 4, "h": 4},
        "SLA Compliance": {"x": 16, "y": 0, "w": 4, "h": 4},
        "Assets": {"x": 20, "y": 0, "w": 4, "h": 4},
        "High-Severity Issues by Domain": {"x": 0, "y": 4, "w": 12, "h": 8},
        "Tickets by Status": {"x": 12, "y": 4, "w": 12, "h": 8},
        "Source Health & Freshness": {"x": 0, "y": 12, "w": 12, "h": 8},
        "Attention Required": {"x": 12, "y": 12, "w": 12, "h": 8},
    }
    for title, grid_pos in expected_layout.items():
        assert panels[title]["gridPos"] == grid_pos

    for title in (
        "Overall Health",
        "Security Alerts",
        "Open Tickets",
        "Overdue Tickets",
        "SLA Compliance",
        "Assets",
    ):
        assert panels[title]["type"] == "stat"
    for title in ("High-Severity Issues by Domain", "Tickets by Status"):
        assert panels[title]["type"] == "piechart"
    for title in ("Source Health & Freshness", "Attention Required"):
        assert panels[title]["type"] == "table"

    query_text = json.dumps(
        [target for panel in dashboard["panels"] for target in panel.get("targets", [])]
    )
    for field in {
        "overall_health_percent",
        "security_alerts",
        "tickets_open",
        "overdue_open",
        "resolution_sla_compliance_percent",
        "assets_total",
        "alert_category_distribution",
        "ticket_status_distribution",
        "attention_required",
    }:
        assert field in query_text

    freshness_target = panels["Source Health & Freshness"]["targets"][0]
    assert freshness_target["root_selector"] == "$.sources"
    assert {column["selector"] for column in freshness_target["columns"]} == {
        "source",
        "health.status",
        "is_stale",
        "health.last_success_at",
    }

    attention_target = panels["Attention Required"]["targets"][0]
    assert {column["selector"] for column in attention_target["columns"]} == {
        "source",
        "issue",
        "count",
    }


def test_executive_dashboard_uses_render_ready_backend_rows() -> None:
    dashboard = load_dashboard()
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    for title in (
        "Overall Health",
        "Security Alerts",
        "Open Tickets",
        "Overdue Tickets",
        "SLA Compliance",
        "Assets",
    ):
        assert panels[title]["targets"][0]["root_selector"] == "$append([], $.summary)"

    assert (
        panels["High-Severity Issues by Domain"]["targets"][0]["root_selector"]
        == "$.alert_category_distribution"
    )
    assert (
        panels["Tickets by Status"]["targets"][0]["root_selector"]
        == "$.ticket_status_distribution"
    )
    assert panels["Source Health & Freshness"]["targets"][0]["root_selector"] == "$.sources"
    assert panels["Attention Required"]["targets"][0]["root_selector"] == "$.attention_required"

    root_selectors = [
        target["root_selector"]
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    ]
    assert all("$sum(" not in selector for selector in root_selectors)
    assert all("$count(" not in selector for selector in root_selectors)
    assert all("$map(" not in selector for selector in root_selectors)


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
