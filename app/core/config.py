from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.contracts import IntegrationSource


PLACEHOLDER_SECRET = "replace-with-a-long-random-secret"
IntegrationConfigState = Literal["configured", "not_configured"]


class Settings(BaseSettings):
    """Application settings loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_secret_key: str = PLACEHOLDER_SECRET
    database_url: str = "postgresql+psycopg://monitoring:replace-me@postgresql:5432/monitoring"
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    session_refresh_seconds: int = 60
    login_window_seconds: int = 300
    login_max_failures: int = 5
    cookie_secure: bool = False

    wazuh_base_url: AnyHttpUrl | None = None
    wazuh_username: str | None = None
    wazuh_password: SecretStr | None = None
    wazuh_verify_tls: bool = True
    wazuh_ca_bundle: Path | None = None
    wazuh_timeout_seconds: int = Field(default=10, ge=1, le=60)

    wazuh_indexer_base_url: AnyHttpUrl | None = None
    wazuh_indexer_username: str | None = None
    wazuh_indexer_password: SecretStr | None = None
    wazuh_indexer_verify_tls: bool = True
    wazuh_indexer_ca_bundle: Path | None = None
    wazuh_indexer_timeout_seconds: int = Field(default=10, ge=1, le=60)

    zabbix_base_url: AnyHttpUrl | None = None
    zabbix_api_token: SecretStr | None = None
    zabbix_verify_tls: bool = True
    zabbix_ca_bundle: Path | None = None
    zabbix_timeout_seconds: int = Field(default=10, ge=1, le=60)

    snipe_it_base_url: AnyHttpUrl | None = None
    snipe_it_api_token: SecretStr | None = None
    snipe_it_verify_tls: bool = True
    snipe_it_ca_bundle: Path | None = None
    snipe_it_timeout_seconds: int = Field(default=10, ge=1, le=60)

    freshservice_base_url: AnyHttpUrl | None = None
    freshservice_api_key: SecretStr | None = None
    freshservice_verify_tls: bool = True
    freshservice_ca_bundle: Path | None = None
    freshservice_timeout_seconds: int = Field(default=10, ge=1, le=60)

    @field_validator(
        "wazuh_base_url",
        "wazuh_username",
        "wazuh_password",
        "wazuh_ca_bundle",
        "wazuh_indexer_base_url",
        "wazuh_indexer_username",
        "wazuh_indexer_password",
        "wazuh_indexer_ca_bundle",
        "zabbix_base_url",
        "zabbix_api_token",
        "zabbix_ca_bundle",
        "snipe_it_base_url",
        "snipe_it_api_token",
        "snipe_it_ca_bundle",
        "freshservice_base_url",
        "freshservice_api_key",
        "freshservice_ca_bundle",
        mode="before",
    )
    @classmethod
    def empty_string_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "wazuh_base_url",
        "wazuh_indexer_base_url",
        "zabbix_base_url",
        "snipe_it_base_url",
        "freshservice_base_url",
    )
    @classmethod
    def reject_url_userinfo(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is not None and (value.username is not None or value.password is not None):
            raise ValueError("integration base URL must not contain userinfo")
        return value

    def wazuh_server_config_state(self) -> IntegrationConfigState:
        required = (self.wazuh_base_url, self.wazuh_username, self.wazuh_password)
        return "configured" if all(value is not None for value in required) else "not_configured"

    def wazuh_indexer_config_state(self) -> IntegrationConfigState:
        required = (
            self.wazuh_indexer_base_url,
            self.wazuh_indexer_username,
            self.wazuh_indexer_password,
        )
        return "configured" if all(value is not None for value in required) else "not_configured"

    def integration_config_state(self, source: IntegrationSource) -> IntegrationConfigState:
        if source == "wazuh":
            return (
                "configured"
                if self.wazuh_server_config_state() == "configured"
                and self.wazuh_indexer_config_state() == "configured"
                else "not_configured"
            )

        required = {
            "zabbix": (self.zabbix_base_url, self.zabbix_api_token),
            "snipe_it": (self.snipe_it_base_url, self.snipe_it_api_token),
            "freshservice": (self.freshservice_base_url, self.freshservice_api_key),
        }
        return "configured" if all(value is not None for value in required[source]) else "not_configured"

    @model_validator(mode="after")
    def validate_secret(self) -> "Settings":
        if self.app_env == "production" and (
            self.app_secret_key == PLACEHOLDER_SECRET or len(self.app_secret_key) < 32
        ):
            raise ValueError(
                "APP_SECRET_KEY must be a non-placeholder secret of at least 32 characters in production"
            )

        if self.app_env == "production":
            wazuh_tls_checks = (
                (self.wazuh_server_config_state(), self.wazuh_verify_tls, "WAZUH_VERIFY_TLS"),
                (
                    self.wazuh_indexer_config_state(),
                    self.wazuh_indexer_verify_tls,
                    "WAZUH_INDEXER_VERIFY_TLS",
                ),
            )
            for config_state, verify_tls, env_name in wazuh_tls_checks:
                if config_state == "configured" and not verify_tls:
                    raise ValueError(
                        f"{env_name} must be true for configured production integrations"
                    )

            tls_checks = {
                "zabbix": (self.zabbix_verify_tls, "ZABBIX_VERIFY_TLS"),
                "snipe_it": (self.snipe_it_verify_tls, "SNIPE_IT_VERIFY_TLS"),
                "freshservice": (self.freshservice_verify_tls, "FRESHSERVICE_VERIFY_TLS"),
            }
            for source, (verify_tls, env_name) in tls_checks.items():
                if self.integration_config_state(source) == "configured" and not verify_tls:
                    raise ValueError(
                        f"{env_name} must be true for configured production integrations"
                    )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
