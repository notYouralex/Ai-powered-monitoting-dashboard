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


def test_app_assets_are_not_exposed_through_open_directory_routes(auth_env) -> None:
    assert auth_env.client.get("/app/assets").status_code == 404
    assert auth_env.client.get("/app/assets/").status_code == 404


def test_existing_ai_page_remains_available(auth_env) -> None:
    response = auth_env.client.get("/ai")

    assert response.status_code == 200
    assert "AI Investigation" in response.text
    assert 'href="/ai/assets/app.css"' in response.text
    assert 'src="/ai/assets/app.js"' in response.text
