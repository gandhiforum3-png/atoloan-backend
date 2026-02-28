"""
Centralised application settings loaded from environment / .env file.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database
    database_url: str = ""
    pghost: str = "localhost"
    pgport: int = 5432
    pguser: str = ""
    pgpassword: str = ""
    pgdatabase: str = "atoloan"

    # OpenAI
    openai_api_key: str = ""

    # 700Credit
    sevencredit_env: str = "test"
    sevencredit_account: str = ""
    sevencredit_password: str = ""
    sevencredit_client_id: str = ""
    sevencredit_client_secret: str = ""

    # CORS allowed origins (comma-separated)
    cors_origins: str = "http://localhost:5173,http://localhost:5174"

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
