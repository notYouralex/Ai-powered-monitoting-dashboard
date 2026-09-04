import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "deployment" / "grafana-operations-handover.md"
README = ROOT / "grafana" / "README.md"

DASHBOARD_INVENTORY = {
    "wazuh.json": ("Wazuh Security", "monitoring-wazuh", "30s"),
    "zabbix-infrastructure.json": ("Zabbix Infrastructure", "monitoring-zabbix", "30s"),
    "snipe-it.json": ("Snipe-IT Asset Management", "monitoring-snipe-it", "1m"),
    "freshservice.json": (
        "Freshservice Service Management",
        "monitoring-freshservice",
        "1m",
    ),
    "executive.json": ("Executive Overview", "monitoring-executive", "1m"),
    "ai-summary.json": ("AI Monitoring Summary", "monitoring-ai-summary", "5m"),
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_grafana_operations_handover_is_step_by_step_and_complete() -> None:
    runbook = read(RUNBOOK)

    required_sections = (
        "Before you start",
        "Golden rules",
        "Dashboard inventory",
        "Monitoring API datasource",
        "Plugin verification",
        "Import or restore the project dashboards",
        "Dashboard-by-dashboard acceptance",
        "Daily operator checks",
        "Troubleshooting decision tree",
        "Rollback and recovery",
        "Final handover checklist",
        "Stop conditions",
    )
    for section in required_sections:
        assert section in runbook

    for dashboard in (
        "Wazuh Security",
        "Zabbix Infrastructure",
        "Snipe-IT Asset Management",
        "Freshservice Service Management",
        "Executive Overview",
        "AI Monitoring Summary",
    ):
        assert dashboard in runbook


def test_grafana_operations_handover_inventory_matches_dashboard_json() -> None:
    runbook = read(RUNBOOK)

    for filename, (title, uid, refresh) in DASHBOARD_INVENTORY.items():
        dashboard = json.loads(
            (ROOT / "grafana" / "dashboards" / filename).read_text(encoding="utf-8")
        )
        assert dashboard["title"] == title
        assert dashboard["uid"] == uid
        assert dashboard["refresh"] == refresh
        assert f"`grafana/dashboards/{filename}`" in runbook
        assert title in runbook
        assert f"`{uid}`" in runbook
        assert refresh in runbook


def test_grafana_operations_handover_uses_canonical_api_and_secure_datasource() -> None:
    runbook = read(RUNBOOK)

    assert "Monitoring API" in runbook
    assert "http://127.0.0.1:8000" in runbook
    assert "GRAFANA_API_TOKEN" in runbook
    assert "secure bearer token field" in runbook.lower()
    assert "Do not paste" in runbook

    for endpoint in (
        "/api/dashboard/wazuh",
        "/api/dashboard/zabbix",
        "/api/dashboard/snipe-it",
        "/api/dashboard/freshservice",
        "/api/dashboard/executive",
        "/api/ai/insights/dashboard",
        "/api/integrations/health",
    ):
        assert endpoint in runbook

    assert "api_jsonrpc.php" not in runbook
    assert "host.get" not in runbook


def test_grafana_operations_handover_documents_plugins_and_runtime_caveats() -> None:
    runbook = read(RUNBOOK)

    assert "yesoreyeram-infinity-datasource" in runbook
    assert "tamirsuliman-weathermap-panel" in runbook
    assert "1.6.12" in runbook
    assert "grafana cli plugins ls" in runbook
    assert "not authoritative" in runbook.lower()
    assert "*:3000" in runbook
    assert "temporary pre-deployment state" in runbook.lower()
    assert "next week" not in runbook.lower()


def test_grafana_operations_handover_is_safe_and_reversible() -> None:
    runbook = read(RUNBOOK)

    assert "do not disable tls verification" in runbook.lower()
    assert "do not commit" in runbook.lower()
    assert "private key" in runbook.lower()
    assert "backup" in runbook.lower()
    assert "rollback" in runbook.lower()
    assert "stop here" in runbook.lower()
    assert "sudo systemctl restart grafana-server" not in runbook
    assert "sudo systemctl reload grafana-server" not in runbook


def test_grafana_readme_points_operators_to_handover_runbook() -> None:
    readme = read(README)

    assert "docs/deployment/grafana-operations-handover.md" in readme
    assert "operations and handover" in readme.lower()
