import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_FILE = ROOT / "grafana" / "dashboards" / "executive.json"
AI_EXECUTIVE_URL = "/api/ai/insights/executive?from=${__from:date:iso}&to=${__to:date:iso}"

pytestmark = pytest.mark.skip(
    reason="Preparation only: enable after the Milestone 5A AI API contract is merged"
)


def load_dashboard() -> dict:
    return json.loads(DASHBOARD_FILE.read_text(encoding="utf-8"))


def test_executive_ai_summary_panel_uses_monitoring_api_contract() -> None:
    dashboard = load_dashboard()
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    assert "AI Insight (Summary)" in panels
    panel = panels["AI Insight (Summary)"]
    assert panel["datasource"]["uid"] == "${DS_MONITORING_API}"

    assert len(panel["targets"]) == 1
    target = panel["targets"][0]
    assert target["datasource"]["uid"] == "${DS_MONITORING_API}"
    assert target["url"] == AI_EXECUTIVE_URL
    assert target["url_options"]["method"] == "GET"
    assert "Authorization" not in json.dumps(target)


def test_executive_ai_summary_panel_uses_bounded_backend_output_only() -> None:
    dashboard = load_dashboard()
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    panel = panels["AI Insight (Summary)"]
    panel_text = json.dumps(panel).lower()

    assert "analysis" in panel_text
    assert "summary" in panel_text
    assert "confidence" in panel_text

    assert "/api/ai/insights/snipe-it" not in panel_text
    assert "/api/ai/insights/freshservice" not in panel_text
    assert "/api/dashboard/wazuh" not in panel_text
    assert "/api/dashboard/zabbix" not in panel_text
    assert "/api/dashboard/snipe-it" not in panel_text
    assert "/api/dashboard/freshservice" not in panel_text

    assert "ollama" not in panel_text
    assert "/api/generate" not in panel_text
    assert "127.0.0.1:11434" not in panel_text
    assert "localhost:11434" not in panel_text
