from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_agents_file_enforces_domain_ownership_and_shared_executive_boundary() -> None:
    text = (ROOT / "AGENTS.md").read_text()

    assert "Wazuh and Freshservice" in text
    assert "Zabbix and Snipe-IT" in text
    assert "Executive dashboard" in text
    assert "raw source" in text
    assert "read-only" in text
    assert "CODEOWNERS" in text
    assert "verified GitHub" in text


def test_human_collaboration_rules_define_shared_change_protocol() -> None:
    text = (ROOT / "docs/development/collaboration-rules.md").read_text()

    assert "Ownership Matrix" in text
    assert "Shared-Change Protocol" in text
    assert "Migration Coordination" in text
    assert "Definition of Done" in text
    assert "WAZUH_" in text
    assert "FRESHSERVICE_" in text
    assert "ZABBIX_" in text
    assert "SNIPE_IT_" in text
    assert "Do not modify another intern's owned integration directly" in text
