"""
Service-to-service auth for routes only dealer-hub-backend may call.
"""
import hmac

from fastapi import Header, HTTPException

from app.core.config import get_settings


def is_service_caller(x_service_token: str) -> bool:
    expected = get_settings().service_token
    # Fail closed: an unset token must never match an empty header.
    return bool(expected) and hmac.compare_digest(x_service_token, expected)


def require_service_token(x_service_token: str = Header(default="")) -> None:
    if not is_service_caller(x_service_token):
        raise HTTPException(status_code=401, detail="not authorized")
