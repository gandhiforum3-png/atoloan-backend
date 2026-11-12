"""
Rate sheet upload and parsing endpoints.
"""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.security import require_service_token

from app.services.rate_sheet_parser import parse_rate_sheet_pdf

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rate-sheets"], dependencies=[Depends(require_service_token)])

MAX_RATE_SHEET_BYTES = 20 * 1024 * 1024


@router.post("/ratesheetuploader")
async def ratesheetuploader(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" not in content_type and "application/x-www-form-urlencoded" not in content_type:
        # Raw body path — nothing to parse
        await request.body()
        return {"status": "ok"}

    form = await request.form()
    data: dict = {}
    files: list = []

    for key, value in form.multi_items():
        if not hasattr(value, "filename"):
            data.setdefault(key, []).append(value)
            continue

        filename = Path(value.filename).name
        content = await value.read()
        if len(content) > MAX_RATE_SHEET_BYTES:
            raise HTTPException(status_code=413, detail="rate sheet exceeds 20 MB")
        parse_error = None
        rate_sheet_data = None

        if value.content_type == "application/pdf" or filename.lower().endswith(".pdf"):
            try:
                rate_sheet_data = (await parse_rate_sheet_pdf(content)).model_dump()
            except ValueError as exc:  # our own, user-safe messages
                parse_error = str(exc)
                logger.exception("Rate sheet parse failed for %s", filename)
            except Exception:
                parse_error = "rate sheet could not be parsed"
                logger.exception("Rate sheet parse failed for %s", filename)

        files.append({"filename": filename, "parse_error": parse_error, "rate_sheet": rate_sheet_data})

    logger.info("ratesheetuploader completed: %d files processed", len(files))
    return {"status": "ok", "fields": data, "files": files}
