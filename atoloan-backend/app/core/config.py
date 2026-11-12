"""
Centralised application settings.

Secret loading priority (highest → lowest):
  1. Environment variables  — set by Vault Agent sidecar in Kubernetes
                              (sources /vault/secrets/*.env before uvicorn starts)
  2. .env file              — used for local development only; silently ignored
                              when absent (e.g. inside a container)

Non-secret config (PGHOST, PGPORT, PGDATABASE, SEVENCREDIT_ENV, CORS_ORIGINS)
is supplied via the Kubernetes ConfigMap (atoloan-infra/k8s) for
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

    # Shared secret dealer-hub-backend sends as X-Service-Token to reach the
    # lender-data routes. Empty = those routes refuse every request.
    service_token: str = ""

    # dealer-hub-backend, called back (with service_token) for a dealer's bank
    # network so their pulls only match banks they work with. Default = dev.sh port.
    dealer_hub_base_url: str = "http://localhost:8001"

    # Cloudflare Turnstile secret. When set, /auth/request-code (the only
    # anonymous entry point) must carry a valid captcha_token.
    turnstile_secret_key: str = ""

    # Customer sign-in. CUSTOMER_AUTH_SECRET keys the HMAC of emailed codes;
    # SES_FROM_EMAIL is the verified SES sender. Both required when APP_ENV is set.
    customer_auth_secret: str = ""
    ses_from_email: str = ""
    # Secure session cookie; false only for local http dev
    customer_cookie_secure: bool = True

    # Deployment name from the ConfigMap (dev/uat/prod); empty = local dev.
    # Safety checks that are optional locally (captcha) fail closed when set.
    app_env: str = ""

    # Swagger UI / OpenAPI schema — on for local dev only
    enable_docs: bool = False

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
