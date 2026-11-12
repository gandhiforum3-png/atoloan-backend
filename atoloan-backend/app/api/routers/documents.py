"""
User document upload endpoint (driver's license + paycheck).
"""
import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text

from app.core.config import get_settings
from app.core.customer_session import get_current_customer
from app.db import get_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


def _sniff_type(content: bytes) -> tuple[str, str] | None:
    """(content_type, extension) from the file's magic bytes; None if not an allowed type."""
    if content.startswith(b"%PDF-"):
        return "application/pdf", ".pdf"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if content[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1"):
        return "image/heic", ".heic"
    return None


@router.post("/me/applications/{application_id}/documents")
async def upload_application_documents(
    application_id: int, request: Request, customer: dict = Depends(get_current_customer)
) -> dict:
    """
    Upload or replace the signed-in customer's documents for one of their own
    applications. multipart/form-data with either or both of:
    - drivers_license, paycheck: PDF, JPEG, PNG or HEIC, up to 10 MB each
    Only the files sent are replaced. Another customer's application → 404.
    """
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        raise HTTPException(status_code=400, detail="Content-Type must be multipart/form-data")

    if not await _owns_application(application_id, customer["email"]):
        raise HTTPException(status_code=404, detail="application not found")

    form = await request.form()
    provided = [
        (name, form.get(name)) for name in _FIELD_TO_COLUMN
        if getattr(form.get(name), "filename", None)
    ]
    if not provided:
        raise HTTPException(status_code=400, detail="attach a driver's license or paycheck file")

    settings = get_settings()
    if not settings.s3_bucket_name:
        raise HTTPException(status_code=500, detail="document storage is not configured")

    s3_client = boto3.client("s3", region_name=settings.aws_region)

    uploaded_files: list = []
    errors: list = []

    for field_name, file_field in provided:
        content = await file_field.read(MAX_DOCUMENT_BYTES + 1)
        if len(content) > MAX_DOCUMENT_BYTES:
            errors.append(f"{field_name} exceeds 10 MB")
            continue
        sniffed = _sniff_type(content)
        if sniffed is None:
            errors.append(f"{field_name} must be a PDF, JPEG, PNG or HEIC file")
            continue
        detected_type, _extension = sniffed

        # Key built only from server-controlled values — never the client filename.
        # One key per application + document: a replacement becomes a new version
        # of the same object (old versions expire via the bucket lifecycle rule —
        # the app's S3 role is write-only by design, so it can't delete).
        key = f"applications/{application_id}/{field_name}"
        try:
            s3_client.put_object(
                Bucket=settings.s3_bucket_name,
                Key=key,
                Body=content,
                ContentType=detected_type,
                ServerSideEncryption="AES256",
            )
        except (BotoCoreError, ClientError):
            msg = f"Failed to upload {field_name}"
            errors.append(msg)
            logger.exception(msg)
            continue

        uploaded_files.append({"field": field_name, "key": key, "size": len(content)})
        logger.info("Uploaded %s for application %s", field_name, application_id)

    if uploaded_files:
        try:
            await _save_document_keys(application_id=application_id, uploaded_files=uploaded_files)
        except Exception as exc:
            # The file is in S3 but not on the application: say so, never "received"
            logger.exception("Failed to record document keys for application %s", application_id)
            raise HTTPException(status_code=503, detail="we couldn't record your documents, please try again") from exc
        status = "partial" if errors else "success"
        return {"status": status, "files": uploaded_files, "errors": errors}

    raise HTTPException(status_code=400, detail=f"No documents uploaded: {'; '.join(errors)}")


async def _owns_application(application_id: int, email: str) -> bool:
    """Only applications the customer ran while signed in are theirs."""
    async with get_engine().connect() as conn:
        found = await conn.scalar(
            text("SELECT 1 FROM loan_applications WHERE id = :id AND customer_email = :email"),
            {"id": application_id, "email": email},
        )
    return found is not None


_FIELD_TO_COLUMN = {
    "drivers_license": "drivers_license_key",
    "paycheck": "paycheck_key",
}


async def _save_document_keys(*, application_id: int, uploaded_files: list) -> None:
    """Record the S3 keys on the signed-in customer's own application.
    Never on users-by-email: /findback takes the email unverified, so keying
    documents by email would let anyone attach files to someone else's record."""
    keys_by_column = {
        _FIELD_TO_COLUMN[f["field"]]: f["key"] for f in uploaded_files if f["field"] in _FIELD_TO_COLUMN
    }
    if not keys_by_column:
        return

    async with get_engine().begin() as conn:
        await conn.execute(
            text("""
                UPDATE loan_applications SET
                    drivers_license_key = COALESCE(:drivers_license_key, drivers_license_key),
                    paycheck_key        = COALESCE(:paycheck_key, paycheck_key)
                WHERE id = :id
            """),
            {
                "id": application_id,
                "drivers_license_key": keys_by_column.get("drivers_license_key"),
                "paycheck_key": keys_by_column.get("paycheck_key"),
            },
        )
    logger.info("Saved document keys: %s", list(keys_by_column))
