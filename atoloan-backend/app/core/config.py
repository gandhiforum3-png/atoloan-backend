"""
Centralised application settings.

Secret loading priority (highest → lowest):
  1. Environment variables  — set by Vault Agent sidecar in Kubernetes
                              (sources /vault/secrets/*.env before uvicorn starts)
  2. .env file              — used for local development only; silently ignored
                              when absent (e.g. inside a container)

Non-secret config (PGHOST, PGPORT, PGDATABASE, SEVENCREDIT_ENV, CORS_ORIGINS)
is supplied via the Kubernetes ConfigMap (backend.yaml / backend-dev.yaml) for
deployed environments and via the .env file locally.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    # Database
    database_url: str = ""
    pghost: str = "localhost"
    pgport: int = 5432
    pguser: str = ""
    pgpassword: str = ""
    pgdatabase: str = "atoloan"

    # Anthropic
    anthropic_api_key: str = ""

    # OpenAI (kept for backward-compat; no longer used by rate_sheet_parser)
    openai_api_key: str = ""

    # 700Credit
    sevencredit_env: str = "test"
    sevencredit_account: str = ""
    sevencredit_password: str = ""
    sevencredit_client_id: str = ""
    sevencredit_client_secret: str = ""

    # AWS / S3 (user-uploaded documents)
    aws_region: str = "us-east-2"
    s3_bucket_name: str = ""

    # CORS allowed origins (comma-separated)
    # Set via CORS_ORIGINS env var (ConfigMap) or .env for local dev
    cors_origins: str = "http://localhost:5173,http://localhost:5174"

    model_config = SettingsConfigDict(
        # env_file is silently ignored when the file does not exist,
        # so this is safe inside containers where there is no .env file.
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
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
