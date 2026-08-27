import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_FILE = ROOT / "grafana" / "dashboards" / "ai-summary.json"
README_FILE = ROOT / "grafana" / "README.md"
COMBINED_URL = "/api/ai/insights/dashboard?from=${__from:date:iso}&to=${__to:date:iso}"


ROOT_SELECTORS = {
    "Executive AI Summary": "$append([], $.executive)",
    "Wazuh AI Summary": "$append([], $.wazuh)",
    "Zabbix AI Summary": "$append([], $.zabbix)",
    "Snipe-IT AI Summary": "$append([], $.snipe_it)",
    "Freshservice AI Summary": "$append([], $.freshservice)",
}


def load_dashboard() -> dict:
    return json.loads(DASHBOARD_FILE.read_text(encoding="utf-8"))


def test_ai_summary_dashboard_contains_all_five_summaries() -> None:
    dashboard = load_dashboard()

    assert dashboard["uid"] == "monitoring-ai-summary"
    assert dashboard["title"] == "AI Monitoring Summary"
    assert dashboard["refresh"] == "5m"
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

    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    assert set(panels) == set(ROOT_SELECTORS)
    assert panels["Executive AI Summary"]["gridPos"] == {"x": 0, "y": 0, "w": 24, "h": 6}
    assert panels["Wazuh AI Summary"]["gridPos"] == {"x": 0, "y": 6, "w": 12, "h": 6}
    assert panels["Zabbix AI Summary"]["gridPos"] == {"x": 12, "y": 6, "w": 12, "h": 6}
    assert panels["Snipe-IT AI Summary"]["gridPos"] == {"x": 0, "y": 12, "w": 12, "h": 6}
    assert panels["Freshservice AI Summary"]["gridPos"] == {"x": 12, "y": 12, "w": 12, "h": 6}

    for title, root_selector in ROOT_SELECTORS.items():
        panel = panels[title]
        assert panel["type"] == "table"
        target = panel["targets"][0]
        assert target["datasource"]["uid"] == "${DS_MONITORING_API}"
        assert target["parser"] == "backend"
        assert target["root_selector"] == root_selector
        assert target["url"] == COMBINED_URL
        assert target["url_options"]["method"] == "GET"
        assert [column["selector"] for column in target["columns"]] == [
            "summary",
            "confidence",
        ]
        assert panel["options"]["cellHeight"] == "lg"
        assert panel["options"]["showHeader"] is True
        if title == "Executive AI Summary":
            assert panel["options"]["enablePagination"] is False
        defaults = panel["fieldConfig"]["defaults"]["custom"]
        assert defaults["align"] == "left"
        assert defaults["wrapText"] is True
        assert defaults["cellOptions"]["type"] == "auto"

        overrides = {
            item["matcher"]["options"]: item["properties"]
            for item in panel["fieldConfig"]["overrides"]
        }
        assert set(overrides) == {"Summary", "Confidence"}
        confidence_properties = {
            item["id"]: item.get("value") for item in overrides["Confidence"]
        }
        assert confidence_properties["custom.width"] == 120
        assert confidence_properties["custom.align"] == "center"
        assert confidence_properties["custom.cellOptions"]["type"] == "color-background"
        if title == "Executive AI Summary":
            assert confidence_properties["custom.cellOptions"]["mode"] == "gradient"
        mappings = confidence_properties["mappings"]
        assert mappings[0]["options"]["high"]["color"] == "green"
        assert mappings[0]["options"]["medium"]["color"] == "yellow"
        assert mappings[0]["options"]["low"]["color"] == "red"
        assert "Authorization" not in json.dumps(target)

    query_text = json.dumps([panel["targets"] for panel in dashboard["panels"]])
    assert "/api/ai/insights/executive" not in query_text
    assert "/api/ai/insights/wazuh" not in query_text
    assert "/api/ai/insights/zabbix" not in query_text
    assert "/api/ai/insights/snipe-it" not in query_text
    assert "/api/ai/insights/freshservice" not in query_text


def test_grafana_readme_lists_combined_ai_summary_dashboard() -> None:
    readme = README_FILE.read_text(encoding="utf-8")

    assert "grafana/dashboards/ai-summary.json" in readme
    assert "AI Monitoring Summary" in readme
    assert "/api/ai/insights/dashboard" in readme
