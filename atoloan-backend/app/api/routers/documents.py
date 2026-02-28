"""
User document upload endpoint (driver's license + paycheck).
"""
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])

UPLOAD_DIR = Path("user_uploaded_documents")


@router.post("/uploadDocuments")
async def upload_documents(request: Request) -> dict:
    """
    Accept multipart/form-data with:
    - drivers_license: image file
    - paycheck: image or PDF file
    - user_email: (optional) used for folder naming
    - user_name: (optional) used for folder naming
    """
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        raise HTTPException(status_code=400, detail="Content-Type must be multipart/form-data")

    form = await request.form()

    user_name = str(form.get("user_name", "unknown"))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c if c.isalnum() else "_" for c in user_name)
    submission_dir = UPLOAD_DIR / f"{timestamp}_{safe_name}"
    submission_dir.mkdir(parents=True, exist_ok=True)

    uploaded_files: list = []
    errors: list = []

    for field_name in ("drivers_license", "paycheck"):
        file_field = form.get(field_name)
        if file_field and hasattr(file_field, "filename") and file_field.filename:
            try:
                raw_name = Path(file_field.filename).name
                safe_filename = f"{field_name}_{raw_name}"
                target = submission_dir / safe_filename
                content = await file_field.read()
                target.write_bytes(content)
                uploaded_files.append(
                    {
                        "field": field_name,
                        "filename": safe_filename,
                        "path": str(target),
                        "size": len(content),
                    }
                )
                logger.info("Saved %s: %s", field_name, target)
            except Exception:
                msg = f"Failed to save {field_name}"
                errors.append(msg)
                logger.exception(msg)
        else:
            errors.append(f"{field_name} file is required")

    submission_id = f"{timestamp}_{safe_name}"

    if len(uploaded_files) == 2:
        return {"status": "success", "message": "Documents uploaded successfully", "submission_id": submission_id, "files": uploaded_files}

    if uploaded_files:
        return {"status": "partial", "message": "Some documents uploaded", "submission_id": submission_id, "files": uploaded_files, "errors": errors}

    raise HTTPException(status_code=400, detail=f"No documents uploaded: {'; '.join(errors)}")
