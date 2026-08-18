import pytest


def test_production_rejects_placeholder_secret() -> None:
    from app.core.config import Settings

    with pytest.raises(ValueError, match="APP_SECRET_KEY"):
        Settings(
            app_env="production",
            app_secret_key="replace-with-a-long-random-secret",
            database_url="sqlite:///test.db",
            cookie_secure=True,
            _env_file=None,
        )


def test_development_accepts_explicit_non_placeholder_secret() -> None:
    from app.core.config import Settings

    settings = Settings(
        app_env="development",
        app_secret_key="a" * 48,
        database_url="sqlite:///test.db",
        _env_file=None,
    )

    assert settings.session_idle_minutes == 30
    assert settings.login_max_failures == 5
    assert settings.cookie_secure is False


def test_production_requires_secure_cookies() -> None:
    from app.core.config import Settings

    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        Settings(
            app_env="production",
            app_secret_key="p" * 48,
            database_url="sqlite:///test.db",
            cookie_secure=False,
            _env_file=None,
        )


def test_production_rejects_short_grafana_api_token() -> None:
    from app.core.config import Settings

    with pytest.raises(ValueError, match="GRAFANA_API_TOKEN"):
        Settings(
            app_env="production",
            app_secret_key="p" * 48,
            database_url="sqlite:///test.db",
            cookie_secure=True,
            grafana_api_token="too-short",
            _env_file=None,
        )
