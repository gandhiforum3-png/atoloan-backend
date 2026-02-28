"""
Rate sheet upload and parsing endpoints.
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.services.pdf_parser_v2 import parse_pdf
from app.services.pdf_validator import validate_pdf_to_markdown
from app.services.rate_sheet_parser import parse_rate_sheet_from_markdown

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rate-sheets"])

# Dedicated thread pool for blocking LLM / PDF work
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="parser_")

UPLOAD_DIR = Path("upload_pdf")


def _parse_rate_sheet_sync(markdown_content: str) -> dict | None:
    """Synchronous wrapper executed inside the thread-pool executor."""
    try:
        result = parse_rate_sheet_from_markdown(markdown_content)
        if result:
            return result.model_dump()
        return None
    except Exception:
        logger.exception("Rate sheet parsing failed inside executor")
        return None


@router.post("/ratesheetuploader")
async def ratesheetuploader(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" not in content_type and "application/x-www-form-urlencoded" not in content_type:
        # Raw body path — nothing to parse
        await request.body()
        return {"status": "ok"}

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    form = await request.form()
    data: dict = {}
    files: list = []

    for key, value in form.multi_items():
        if not hasattr(value, "filename"):
            data.setdefault(key, []).append(value)
            continue

        filename = Path(value.filename).name
        target = UPLOAD_DIR / filename
        content = await value.read()
        target.write_bytes(content)

        parsed = None
        parse_error = None
        validation = None
        rate_sheet_data = None

        is_pdf = value.content_type == "application/pdf" or filename.lower().endswith(".pdf")

        if is_pdf:
            try:
                parsed = parse_pdf(target)

                markdown_path = Path(parsed.get("markdown_path", ""))
                if markdown_path.exists():
                    try:
                        validation_result = validate_pdf_to_markdown(target, markdown_path)
                        validation = {
                            "is_valid": validation_result["is_valid"],
                            "similarity": f"{validation_result['text_similarity']:.1%}",
                            "error_count": len(validation_result["errors"]),
                            "warning_count": len(validation_result["warnings"]),
                        }
                        if not validation_result["is_valid"]:
                            logger.warning(
                                "PDF validation warning for %s: %s",
                                filename, validation_result["errors"],
                            )
                    except Exception:
                        logger.exception("PDF validation failed for %s", filename)
                        validation = {"error": "validation failed"}

                    try:
                        markdown_content = markdown_path.read_text(encoding="utf-8")
                        loop = asyncio.get_running_loop()
                        rate_sheet_dict = await loop.run_in_executor(
                            _executor, _parse_rate_sheet_sync, markdown_content
                        )
                        if rate_sheet_dict:
                            parsed["rate_sheet_parsed"] = rate_sheet_dict
                            rate_sheet_data = rate_sheet_dict
                            logger.info("Successfully parsed rate sheet from %s", filename)
                        else:
                            logger.warning("Rate sheet parser returned None for %s", filename)
                    except Exception:
                        logger.exception("Rate sheet parsing failed for %s", filename)
                else:
                    logger.warning("Markdown path not found: %s", markdown_path)

            except Exception as exc:
                parse_error = str(exc)
                logger.exception("PDF parse failed for %s", filename)

        files.append(
            {
                "filename": filename,
                "parse_error": parse_error,
                "validation": validation,
                "rate_sheet": rate_sheet_data,
            }
        )

    logger.info("ratesheetuploader completed: %d files processed", len(files))
    return {"status": "ok", "fields": data, "files": files}


@router.get("/ratesheetuploader/markdown/{filename}")
async def download_markdown(filename: str) -> FileResponse:
    upload_dir = UPLOAD_DIR.resolve()
    target = (upload_dir / filename).resolve()
    if upload_dir not in target.parents or target.suffix.lower() != ".md":
        raise HTTPException(status_code=400, detail="invalid markdown file")
    if not target.exists():
        raise HTTPException(status_code=404, detail="markdown file not found")
    return FileResponse(target, media_type="text/markdown", filename=target.name)


@router.post("/parse-rate-sheet-markdown")
async def parse_rate_sheet_markdown(request: Request) -> dict:
    """
    Parse raw markdown text and return a structured CreditUnionRateSheet.

    Payload: { "markdown_text": "...", "current_year": 2026 }
    """
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    markdown_text = payload.get("markdown_text")
    if not markdown_text or not isinstance(markdown_text, str):
        raise HTTPException(
            status_code=400,
            detail="markdown_text is required and must be a non-empty string",
        )

    current_year = payload.get("current_year", 2026)
    if not isinstance(current_year, int) or not (1900 <= current_year <= 2100):
        raise HTTPException(
            status_code=400,
            detail="current_year must be an integer between 1900 and 2100",
        )

    try:
        loop = asyncio.get_running_loop()
        rate_sheet = await loop.run_in_executor(
            _executor,
            lambda: parse_rate_sheet_from_markdown(markdown_text, current_year=current_year),
        )
    except Exception as exc:
        logger.exception("Rate sheet markdown parsing failed")
        raise HTTPException(status_code=500, detail=f"Rate sheet parsing failed: {exc}") from exc

    if rate_sheet is None:
        return {
            "status": "error",
            "error": "Failed to parse rate sheet — content may be invalid or incomplete.",
        }

    return {"status": "success", "result": rate_sheet.model_dump()}
