"""
Thin wrapper around AWS SES for sending transactional email.

Mirrors the boto3 usage pattern already used for S3 document uploads
(app/api/routers/documents.py) — a client is created per call using the
region from Settings, relying on the same IAM credentials already
configured for this service (env vars / instance role / Vault-sourced env).
"""
import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)


def send_email(
    *,
    region: str,
    sender: str,
    to_address: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> None:
    """
    Send a single transactional email via AWS SES.

    Raises on failure (missing credentials, unverified sender/domain, SES
    sandbox restrictions, etc.) — callers that want best-effort behavior
    (e.g. not failing an HTTP request over a bad email) are responsible for
    catching and logging.
    """
    client = boto3.client("ses", region_name=region)
    try:
        client.send_email(
            Source=sender,
            Destination={"ToAddresses": [to_address]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                },
            },
        )
    except (ClientError, BotoCoreError) as exc:
        logger.exception("SES send_email to %s failed: %s", to_address, exc)
        raise
