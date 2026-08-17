import pytest


def test_production_rejects_placeholder_secret() -> None:
    from app.core.config import Settings

    with pytest.raises(ValueError, match="APP_SECRET_KEY"):
        Settings(
            app_env="production",
            app_secret_key="replace-with-a-long-random-secret",
            database_url="sqlite:///test.db",
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


def test_grafana_service_token_is_optional_and_secret() -> None:
    from pydantic import SecretStr

    from app.core.config import Settings

    without_token = Settings(
        app_env="test",
        app_secret_key="a" * 48,
        database_url="sqlite:///test.db",
        _env_file=None,
    )
    with_token = Settings(
        app_env="test",
        app_secret_key="a" * 48,
        database_url="sqlite:///test.db",
        grafana_service_token="g" * 48,
        _env_file=None,
    )

    assert without_token.grafana_service_token is None
    assert isinstance(with_token.grafana_service_token, SecretStr)
    assert with_token.grafana_service_token.get_secret_value() == "g" * 48


def test_configured_grafana_service_token_must_be_long() -> None:
    from app.core.config import Settings

    with pytest.raises(ValueError, match="GRAFANA_SERVICE_TOKEN"):
        Settings(
            app_env="test",
            app_secret_key="a" * 48,
            database_url="sqlite:///test.db",
            grafana_service_token="too-short",
            _env_file=None,
        )
