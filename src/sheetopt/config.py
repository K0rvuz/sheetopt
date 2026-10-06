from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    google_credentials: str | None = None
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_prefix="SHEETOPT_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
