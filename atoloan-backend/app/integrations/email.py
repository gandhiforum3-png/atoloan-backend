"""
Customer sign-in emails via AWS SES. Local dev (no APP_ENV, no sender) logs
instead; a deployed env without a sender refuses rather than skipping.
"""
import logging

import boto3

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_LOGIN_CODE = {
    "en": (
        "Your Atoloans sign-in code",
        "Your Atoloans sign-in code is {code}.\n\nIt expires in 10 minutes. "
        "If you didn't request this, ignore this email — no one can sign in without the code.",
    ),
    "es": (
        "Tu código de acceso de Atoloans",
        "Tu código de acceso de Atoloans es {code}.\n\nVence en 10 minutos. "
        "Si no lo solicitaste, ignora este correo: nadie puede entrar sin el código.",
    ),
}

_DISABLED = {
    "en": (
        "Your Atoloans account is disabled",
        "We received a sign-in request for this email address, but the account is disabled, "
        "so no code was sent.\n\nIf you think this is a mistake, contact Atoloans support. "
        "If you didn't try to sign in, you can ignore this email.",
    ),
    "es": (
        "Tu cuenta de Atoloans está desactivada",
        "Recibimos una solicitud de acceso para este correo, pero la cuenta está desactivada, "
        "así que no enviamos un código.\n\nSi crees que es un error, comunícate con el soporte de Atoloans. "
        "Si no intentaste entrar, puedes ignorar este correo.",
    ),
}


def _send(to: str, subject: str, body: str, dev_note: str) -> None:
    settings = get_settings()
    if not settings.ses_from_email:
        if settings.app_env in ("", "local"):
            logger.warning("DEV email for %s: %s", to, dev_note)
            return
        raise RuntimeError("SES_FROM_EMAIL is not set")
    boto3.client("sesv2", region_name=settings.aws_region).send_email(
        FromEmailAddress=settings.ses_from_email,
        Destination={"ToAddresses": [to]},
        Content={
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
            }
        },
    )


def send_login_code(to: str, code: str, language: str) -> None:
    subject, body = _LOGIN_CODE.get(language, _LOGIN_CODE["en"])
    _send(to, subject, body.format(code=code), f"sign-in code {code}")


def send_disabled_notice(to: str, language: str) -> None:
    """Sent instead of a code for disabled accounts: same SES round trip as a
    code (no timing tell), and the customer learns why they can't sign in."""
    subject, body = _DISABLED.get(language, _DISABLED["en"])
    _send(to, subject, body, "account disabled notice")
