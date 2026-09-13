APP_ROUTES = (
    "/app",
    "/app/executive",
    "/app/wazuh",
    "/app/zabbix",
    "/app/snipe-it",
    "/app/freshservice",
    "/app/ai",
)


def test_app_routes_serve_secure_local_shell(auth_env) -> None:
    for route in APP_ROUTES:
        response = auth_env.client.get(route)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-store"
        assert "default-src 'self'" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"

        body = response.text
        assert "AI-Powered Monitoring" in body
        assert 'id="login-form"' in body
        assert 'id="application-view"' in body
        assert 'href="/app/assets/application.css"' in body
        assert 'src="/app/assets/application.js"' in body
        assert "Executive" in body
        assert "Wazuh" in body
        assert "Zabbix" in body
        assert "Snipe-IT" in body
        assert "Freshservice" in body
        assert "AI Investigation" in body
        assert "https://" not in body
        assert "http://" not in body


def test_app_assets_use_existing_auth_contract_and_safe_browser_patterns(auth_env) -> None:
    css = auth_env.client.get("/app/assets/application.css")
    script = auth_env.client.get("/app/assets/application.js")

    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]

    source = script.text
    for route in (
        "/api/auth/me",
        "/api/auth/login",
        "/api/auth/logout",
    ):
        assert route in source

    for route in APP_ROUTES[1:]:
        assert route in source

    assert 'credentials: "same-origin"' in source
    assert "response.status === 401" in source
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "document.cookie" not in source
    assert "innerHTML" not in source
    assert "https://" not in source
    assert "http://" not in source


def test_executive_web_view_uses_canonical_executive_contract(auth_env) -> None:
    page = auth_env.client.get("/app/executive")
    script = auth_env.client.get("/app/assets/application.js")

    assert page.status_code == 200
    body = page.text
    for element_id in (
        "executive-dashboard-view",
        "executive-status",
        "executive-summary-grid",
        "executive-alert-distribution",
        "executive-ticket-distribution",
        "executive-source-health-body",
        "executive-attention-body",
    ):
        assert f'id="{element_id}"' in body

    source = script.text
    assert "/api/dashboard/executive" in source
    for field in (
        "overall_health_percent",
        "security_alerts",
        "tickets_open",
        "overdue_open",
        "resolution_sla_compliance_percent",
        "assets_total",
        "alert_category_distribution",
        "ticket_status_distribution",
        "attention_required",
        "last_success_at",
        "is_stale",
    ):
        assert field in source

    assert 'executive: "/api/dashboard/executive"' in source


def test_wazuh_web_view_uses_canonical_wazuh_contract(auth_env) -> None:
    page = auth_env.client.get("/app/wazuh")
    script = auth_env.client.get("/app/assets/application.js")

    assert page.status_code == 200
    body = page.text
    for element_id in (
        "wazuh-dashboard-view",
        "wazuh-status",
        "wazuh-summary-grid",
        "wazuh-alert-trend",
        "wazuh-alert-severity",
        "wazuh-mitre-tactics",
        "wazuh-top-alerts-body",
        "wazuh-vulnerability-severity",
        "wazuh-top-agents",
        "wazuh-agent-status",
        "wazuh-recent-alerts-body",
        "wazuh-warnings",
    ):
        assert f'id="{element_id}"' in body

    source = script.text
    assert 'wazuh: "/api/dashboard/wazuh"' in source
    for field in (
        "alerts_total",
        "alerts_critical",
        "alerts_high",
        "alerts_medium",
        "alerts_low",
        "vulnerabilities_total",
        "vulnerabilities_critical",
        "vulnerabilities_high",
        "agents_active",
        "agents_disconnected",
        "agents_pending",
        "agents_never_connected",
        "agents_unknown",
        "alert_trend",
        "top_alerts",
        "top_agents",
        "by_severity",
        "tactics",
        "recent_alerts",
        "is_stale",
        "warnings",
    ):
        assert field in source

    assert "active response" not in source.lower()
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "document.cookie" not in source
    assert "innerHTML" not in source


def test_zabbix_web_view_uses_canonical_zabbix_contract(auth_env) -> None:
    page = auth_env.client.get("/app/zabbix")
    script = auth_env.client.get("/app/assets/application.js")

    assert page.status_code == 200
    body = page.text
    for element_id in (
        "zabbix-dashboard-view",
        "zabbix-status",
        "zabbix-summary-grid",
        "zabbix-availability",
        "zabbix-problem-severity",
        "zabbix-active-problems-body",
        "zabbix-top-hosts-body",
        "zabbix-cpu-live",
        "zabbix-memory-live",
        "zabbix-network-latency",
        "zabbix-network-bandwidth",
        "zabbix-topology",
        "zabbix-system-info-body",
        "zabbix-warnings",
    ):
        assert f'id="{element_id}"' in body

    source = script.text
    assert 'zabbix: "/api/dashboard/zabbix"' in source
    for field in (
        "hosts_enabled",
        "hosts_disabled",
        "hosts_in_maintenance",
        "interfaces_available",
        "interfaces_unavailable",
        "interfaces_unknown",
        "problems_total",
        "problems_warning",
        "problems_average",
        "problems_high",
        "problems_disaster",
        "resource_pressure",
        "top_affected_hosts",
        "resource_live",
        "resource_trends",
        "network_live",
        "topology_maps",
        "active_problems",
        "is_stale",
        "warnings",
    ):
        assert field in source

    assert "createElementNS" in source
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "document.cookie" not in source
    assert "innerHTML" not in source


def test_snipe_it_web_view_uses_canonical_snipe_it_contract(auth_env) -> None:
    page = auth_env.client.get("/app/snipe-it")
    script = auth_env.client.get("/app/assets/application.js")

    assert page.status_code == 200
    body = page.text
    for element_id in (
        "snipe-it-dashboard-view",
        "snipe-it-status",
        "snipe-it-summary-grid",
        "snipe-it-category-distribution",
        "snipe-it-status-distribution",
        "snipe-it-company-distribution",
        "snipe-it-location-distribution",
        "snipe-it-activity-status",
        "snipe-it-recent-activity-body",
        "snipe-it-warranty-status",
        "snipe-it-warranty-body",
        "snipe-it-warnings",
    ):
        assert f'id="{element_id}"' in body

    source = script.text
    for route in (
        'snipeIt: "/api/dashboard/snipe-it"',
        'snipeItActivity: "/api/dashboard/snipe-it/recent-activity"',
        'snipeItWarranty: "/api/dashboard/snipe-it/warranty-expiry"',
    ):
        assert route in source

    for field in (
        "assets_total",
        "assets_assigned",
        "assets_unassigned",
        "assets_deployed",
        "assets_available",
        "assets_maintenance",
        "assets_retired",
        "assets_missing_serial",
        "assets_missing_asset_tag",
        "warranty_expired",
        "warranty_expiring_soon",
        "category_distribution",
        "status_distribution",
        "company_distribution",
        "location_distribution",
        "activity",
        "warranty_expiry",
        "is_stale",
        "warnings",
    ):
        assert field in source

    assert "activity.location" not in source
    assert "asset update" not in source.lower()
    assert "assign asset" not in source.lower()
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "document.cookie" not in source
    assert "innerHTML" not in source


def test_app_assets_are_not_exposed_through_open_directory_routes(auth_env) -> None:
    assert auth_env.client.get("/app/assets").status_code == 404
    assert auth_env.client.get("/app/assets/").status_code == 404


def test_existing_ai_page_remains_available(auth_env) -> None:
    response = auth_env.client.get("/ai")

    assert response.status_code == 200
    assert "AI Investigation" in response.text
    assert 'href="/ai/assets/app.css"' in response.text
    assert 'src="/ai/assets/app.js"' in response.text
