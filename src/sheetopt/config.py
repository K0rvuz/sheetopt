from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    google_credentials: str | None = None
    admin_token: str | None = None
    encryption_key: str | None = None
    data_dir: str = "/data"
    public_base_url: str = "http://localhost:8080"
    google_copy_timeout_seconds: int = Field(default=180, ge=15, le=600)
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_prefix="SHEETOPT_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
