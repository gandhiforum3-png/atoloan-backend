"""
User document upload endpoint (driver's license + paycheck).
"""
import logging
from datetime import datetime
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from app.core.config import get_settings
from app.db import get_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])


@router.post("/uploadDocuments")
async def upload_documents(request: Request) -> dict:
    """
    Accept multipart/form-data with:
    - drivers_license: image file
    - paycheck: image or PDF file
    - user_email: used to associate the uploaded document keys with a user record
    - first_name, last_name: used when creating a new user record
    - user_name: (optional) used for folder naming
    """
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        raise HTTPException(status_code=400, detail="Content-Type must be multipart/form-data")

    settings = get_settings()
    if not settings.s3_bucket_name:
        raise HTTPException(status_code=500, detail="S3_BUCKET_NAME is not configured")
    s3_client = boto3.client("s3", region_name=settings.aws_region)

    form = await request.form()

    user_email = str(form.get("user_email", "")).strip()
    if not user_email:
        raise HTTPException(status_code=400, detail="user_email is required")
    first_name = str(form.get("first_name", "")).strip()
    last_name = str(form.get("last_name", "")).strip()

    user_name = str(form.get("user_name", "unknown"))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c if c.isalnum() else "_" for c in user_name)
    submission_id = f"{timestamp}_{safe_name}"

    uploaded_files: list = []
    errors: list = []

    for field_name in ("drivers_license", "paycheck"):
        file_field = form.get(field_name)
        if file_field and hasattr(file_field, "filename") and file_field.filename:
            try:
                raw_name = Path(file_field.filename).name
                safe_filename = f"{field_name}_{raw_name}"
                key = f"{submission_id}/{safe_filename}"
                content = await file_field.read()
                s3_client.put_object(
                    Bucket=settings.s3_bucket_name,
                    Key=key,
                    Body=content,
                    ContentType=getattr(file_field, "content_type", None) or "application/octet-stream",
                )
                uploaded_files.append(
                    {
                        "field": field_name,
                        "filename": safe_filename,
                        "key": key,
                        "size": len(content),
                    }
                )
                logger.info("Uploaded %s to s3://%s/%s", field_name, settings.s3_bucket_name, key)
            except (BotoCoreError, ClientError):
                msg = f"Failed to upload {field_name}"
                errors.append(msg)
                logger.exception(msg)
        else:
            errors.append(f"{field_name} file is required")

    if uploaded_files:
        await _save_document_keys(
            user_email=user_email,
            first_name=first_name,
            last_name=last_name,
            uploaded_files=uploaded_files,
        )

    if len(uploaded_files) == 2:
        return {"status": "success", "message": "Documents uploaded successfully", "submission_id": submission_id, "files": uploaded_files}

    if uploaded_files:
        return {"status": "partial", "message": "Some documents uploaded", "submission_id": submission_id, "files": uploaded_files, "errors": errors}

    raise HTTPException(status_code=400, detail=f"No documents uploaded: {'; '.join(errors)}")


_FIELD_TO_COLUMN = {
    "drivers_license": "drivers_license_key",
    "paycheck": "paycheck_key",
}


async def _save_document_keys(
    *, user_email: str, first_name: str, last_name: str, uploaded_files: list
) -> None:
    """Upsert the S3 keys of successfully uploaded documents onto the user's row."""
    keys_by_column = {
        _FIELD_TO_COLUMN[f["field"]]: f["key"] for f in uploaded_files if f["field"] in _FIELD_TO_COLUMN
    }
    if not keys_by_column:
        return

    try:
        async with get_engine().begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO users (email, first_name, last_name, drivers_license_key, paycheck_key)
                    VALUES (:email, :first_name, :last_name, :drivers_license_key, :paycheck_key)
                    ON CONFLICT (email) DO UPDATE SET
                        drivers_license_key = COALESCE(EXCLUDED.drivers_license_key, users.drivers_license_key),
                        paycheck_key         = COALESCE(EXCLUDED.paycheck_key, users.paycheck_key),
                        last_modified_at     = NOW()
                """),
                {
                    "email": user_email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "drivers_license_key": keys_by_column.get("drivers_license_key"),
                    "paycheck_key": keys_by_column.get("paycheck_key"),
                },
            )
        logger.info("Saved document keys for %s: %s", user_email, list(keys_by_column))
    except Exception:
        logger.exception("Failed to save document keys for %s — S3 upload still succeeded", user_email)
