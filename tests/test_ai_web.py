def test_ai_page_serves_local_login_and_chat_shell(auth_env) -> None:
    response = auth_env.client.get("/ai")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"

    body = response.text
    assert "AI Investigation" in body
    assert 'id="login-form"' in body
    assert 'id="chat-form"' in body
    assert 'href="/ai/assets/app.css"' in body
    assert 'src="/ai/assets/app.js"' in body
    assert "https://" not in body
    assert "http://" not in body


def test_ai_page_assets_are_same_origin_and_use_existing_api_contract(auth_env) -> None:
    css = auth_env.client.get("/ai/assets/app.css")
    script = auth_env.client.get("/ai/assets/app.js")

    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]

    source = script.text
    for route in (
        "/api/auth/me",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/ai/query",
    ):
        assert route in source

    assert 'credentials: "same-origin"' in source
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "document.cookie" not in source
    assert "innerHTML" not in source
    assert "https://" not in source
    assert "http://" not in source


def test_ai_page_assets_are_not_exposed_through_open_directory_routes(auth_env) -> None:
    assert auth_env.client.get("/ai/assets").status_code == 404
    assert auth_env.client.get("/ai/assets/").status_code == 404
