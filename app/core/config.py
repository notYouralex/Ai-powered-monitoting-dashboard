from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PLACEHOLDER_SECRET = "replace-with-a-long-random-secret"


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

    @model_validator(mode="after")
    def validate_secret(self) -> "Settings":
        if self.app_env == "production" and (
            self.app_secret_key == PLACEHOLDER_SECRET or len(self.app_secret_key) < 32
        ):
            raise ValueError(
                "APP_SECRET_KEY must be a non-placeholder secret of at least 32 characters in production"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
