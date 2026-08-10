import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make_settings(**overrides):
    values = {
        "app_env": "test",
        "app_secret_key": "t" * 48,
        "database_url": "sqlite:///test.db",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_all_sources_default_to_not_configured() -> None:
    settings = make_settings()

    assert settings.integration_config_state("wazuh") == "not_configured"
    assert settings.integration_config_state("zabbix") == "not_configured"
    assert settings.integration_config_state("snipe_it") == "not_configured"
    assert settings.integration_config_state("freshservice") == "not_configured"


def test_wazuh_configuration_is_independent() -> None:
    settings = make_settings(
        wazuh_base_url="https://wazuh.internal:55000",
        wazuh_username="reader",
        wazuh_password="fake-wazuh-password",
    )

    assert settings.integration_config_state("wazuh") == "configured"
    assert settings.integration_config_state("zabbix") == "not_configured"


def test_blank_required_values_are_treated_as_missing() -> None:
    settings = make_settings(
        zabbix_base_url="",
        zabbix_api_token="",
    )

    assert settings.integration_config_state("zabbix") == "not_configured"


def test_source_defaults_enable_tls_and_use_ten_second_timeout() -> None:
    settings = make_settings()

    assert settings.wazuh_verify_tls is True
    assert settings.zabbix_verify_tls is True
    assert settings.snipe_it_verify_tls is True
    assert settings.freshservice_verify_tls is True
    assert settings.wazuh_timeout_seconds == 10
    assert settings.freshservice_timeout_seconds == 10
    assert settings.freshservice_sync_interval_seconds == 600


@pytest.mark.parametrize("timeout", [0, -1, 61])
def test_source_timeout_must_be_between_one_and_sixty_seconds(timeout: int) -> None:
    with pytest.raises(ValidationError):
        make_settings(wazuh_timeout_seconds=timeout)


@pytest.mark.parametrize("interval", [299, 901])
def test_freshservice_sync_interval_stays_within_approved_window(interval: int) -> None:
    with pytest.raises(ValidationError):
        make_settings(freshservice_sync_interval_seconds=interval)


def test_source_url_rejects_embedded_credentials() -> None:
    with pytest.raises(ValidationError, match="userinfo"):
        make_settings(
            wazuh_base_url="https://user:password@wazuh.internal:55000",
            wazuh_username="reader",
            wazuh_password="fake-wazuh-password",
        )


def test_secret_repr_does_not_expose_values() -> None:
    secret = "fake-zabbix-token-123456789"
    settings = make_settings(
        zabbix_base_url="https://zabbix.internal/api_jsonrpc.php",
        zabbix_api_token=secret,
    )

    assert secret not in repr(settings)
    assert settings.zabbix_api_token is not None
    assert settings.zabbix_api_token.get_secret_value() == secret


def test_production_rejects_disabled_tls_for_configured_source() -> None:
    with pytest.raises(ValidationError, match="WAZUH_VERIFY_TLS"):
        make_settings(
            app_env="production",
            app_secret_key="p" * 48,
            wazuh_base_url="https://wazuh.internal:55000",
            wazuh_username="reader",
            wazuh_password="fake-wazuh-password",
            wazuh_verify_tls=False,
        )


def test_production_allows_disabled_tls_on_unconfigured_source() -> None:
    settings = make_settings(
        app_env="production",
        app_secret_key="p" * 48,
        wazuh_verify_tls=False,
    )

    assert settings.integration_config_state("wazuh") == "not_configured"
