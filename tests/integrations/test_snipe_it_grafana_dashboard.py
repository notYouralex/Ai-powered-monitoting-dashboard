import json
from pathlib import Path


DASHBOARD_PATH = Path("grafana/dashboards/snipe-it.json")


def _panel(dashboard: dict, panel_id: int) -> dict:
    return next(panel for panel in dashboard["panels"] if panel["id"] == panel_id)


def test_snipe_it_dashboard_uses_company_distribution() -> None:
    dashboard = json.loads(DASHBOARD_PATH.read_text())
    panel = _panel(dashboard, 13)

    assert panel["title"] == "Assets by Company"
    assert panel["targets"][0]["root_selector"] == "$.company_distribution"


def test_recent_activity_shows_assigned_to_without_location() -> None:
    dashboard = json.loads(DASHBOARD_PATH.read_text())
    panel = _panel(dashboard, 14)
    columns = panel["targets"][0]["columns"]
    column_labels = {column["selector"]: column["text"] for column in columns}

    assert column_labels["performed_by"] == "Performed By"
    assert column_labels["target"] == "Assigned To"
    assert "location" not in column_labels
    assert panel["options"]["sortBy"] == []
