import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError

from app.db import create_tables, get_engine, test_connection
from app.integrations.seven_hundred import SevenHundredCreditClient
from app.models.user_create import UserCreate
from app.models.user_table import user_table
from app.services.pdf_parser_v2 import parse_pdf
from app.services.pdf_validator import validate_pdf_to_markdown


logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        await create_tables()
        await test_connection()
        logging.info("Database connection successful")
    except Exception:
        logging.exception("Database connection failed on startup")
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://dev.atoloan.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/hello")
async def hello() -> dict:
    return {"message": "hello world"}


@app.get("/db-check")
async def db_check() -> dict:
    try:
        await test_connection()
    except Exception:
        raise HTTPException(status_code=500, detail="database connection failed")
    return {"status": "ok"}


@app.post("/echo")
async def echo(request: Request) -> dict:
    payload = await request.json()
    logging.info("Received payload: %s", payload)
    return {"received": payload}


@app.post("/findback")
async def findback(request: Request) -> dict:
    payload = await request.json()
    logging.info("findback payload: %s", payload)

    if isinstance(payload, dict) and isinstance(payload.get("contactInfo"), dict):
        contact = payload["contactInfo"]
        payload = {
            "first_name": contact.get("firstName"),
            "last_name": contact.get("lastName"),
            "address": contact.get("address"),
            "city": contact.get("city"),
            "state": contact.get("state"),
            "zip_code": contact.get("zip"),
            "bureau": payload.get("bureau"),
            "ssn": payload.get("ssn"),
            "app_modified": payload.get("app_modified"),
            "extra_fields": payload.get("extra_fields"),
        }

    required = ["first_name", "last_name", "address", "city", "state", "zip_code"]
    missing = [key for key in required if not payload.get(key)]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"missing required fields: {', '.join(missing)}",
        )

    try:
        client = SevenHundredCreditClient.from_env()
        result = client.send_prequalify(
            first_name=payload["first_name"],
            last_name=payload["last_name"],
            address=payload["address"],
            city=payload["city"],
            state=payload["state"],
            zip_code=payload["zip_code"],
            bureau=payload.get("bureau", "TU"),
            ssn=payload.get("ssn"),
            app_modified=bool(payload.get("app_modified", False)),
            extra_fields=payload.get("extra_fields"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logging.exception("findback request failed")
        raise HTTPException(status_code=502, detail="findback request failed")

    response = {"prequal": result.to_dict()}
    logging.info("findback response: %s", response)
    return response


@app.post("/validate-zipcode")
async def validate_zipcode(request: Request) -> dict:
    payload = await request.json()
    zipcode = payload.get("zipcode") if isinstance(payload, dict) else None
    if not zipcode:
        raise HTTPException(status_code=400, detail="zipcode is required")

    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT city FROM zipcode WHERE zipcode = :zipcode LIMIT 1"),
            {"zipcode": str(zipcode)},
        )
        row = result.first()
        exists = row is not None
        city = row[0] if row else None

    return {"zipcode": str(zipcode), "valid": exists, "city": city}


@app.post("/ratesheetuploader")
async def ratesheetuploader(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        data = {}
        files = []
        upload_dir = Path("upload_pdf")
        upload_dir.mkdir(parents=True, exist_ok=True)
        for key, value in form.multi_items():
            if hasattr(value, "filename"):
                filename = Path(value.filename).name
                target = upload_dir / filename
                content = await value.read()
                target.write_bytes(content)
                parsed = None
                parse_error = None
                validation = None
                
                if value.content_type == "application/pdf" or filename.lower().endswith(".pdf"):
                    try:
                        # Parse PDF with improved parser
                        parsed = parse_pdf(target)
                        
                        # Optional: Validate the generated markdown
                        try:
                            markdown_path = Path(parsed.get("markdown_path"))
                            validation_result = validate_pdf_to_markdown(target, markdown_path)
                            validation = {
                                "is_valid": validation_result["is_valid"],
                                "similarity": f"{validation_result['text_similarity']:.1%}",
                                "error_count": len(validation_result["errors"]),
                                "warning_count": len(validation_result["warnings"]),
                            }
                            if not validation_result["is_valid"]:
                                logging.warning(
                                    f"PDF validation warning for {filename}: "
                                    f"{validation_result['errors']}"
                                )
                        except Exception as val_exc:
                            logging.warning(f"PDF validation failed for {filename}: {val_exc}")
                            validation = {"error": str(val_exc)}
                            
                    except Exception as exc:
                        parse_error = str(exc)
                        logging.exception("ratesheetuploader pdf parse failed")
                        
                logging.info("ratesheetuploader parsed: %s", parsed)
                files.append(
                    {
                        "field": key,
                        "filename": filename,
                        "content_type": value.content_type,
                        "saved_to": str(target),
                        "parsed": parsed,
                        "parse_error": parse_error,
                        "validation": validation,
                        "markdown_file": (
                            Path(parsed.get("markdown_path")).name
                            if isinstance(parsed, dict) and parsed.get("markdown_path")
                            else None
                        ),
                        "markdown_url": (
                            f"/ratesheetuploader/markdown/{Path(parsed.get('markdown_path')).name}"
                            if isinstance(parsed, dict) and parsed.get("markdown_path")
                            else None
                        ),
                        "markdown_file_content": (
                            Path(parsed.get("markdown_path")).read_text(encoding="utf-8")
                            if isinstance(parsed, dict) and parsed.get("markdown_path")
                            else None
                        ),
                    }
                )
            else:
                data.setdefault(key, []).append(value)
        logging.info("ratesheetuploader form fields: %s", data)
        logging.info("ratesheetuploader files: %s", files)
        return {"status": "ok", "fields": data, "files": files}

    body = await request.body()
    try:
        payload = await request.json()
        logging.info("ratesheetuploader payload: %s", payload)
    except Exception:
        # Some clients send non-UTF8 bytes; log safely.
        text = body.decode("utf-8", errors="replace")
        logging.info("ratesheetuploader payload (raw): %s", text)
    return {"status": "ok"}


@app.get("/ratesheetuploader/markdown/{filename}")
async def download_markdown(filename: str) -> FileResponse:
    upload_dir = Path("upload_pdf").resolve()
    target = (upload_dir / filename).resolve()
    if upload_dir not in target.parents or target.suffix.lower() != ".md":
        raise HTTPException(status_code=400, detail="invalid markdown file")
    if not target.exists():
        raise HTTPException(status_code=404, detail="markdown file not found")
    return FileResponse(target, media_type="text/markdown", filename=target.name)


@app.post("/users")
async def create_user(payload: UserCreate) -> dict:
    engine = get_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                insert(user_table).values(
                    email=payload.email,
                    first_name=payload.first_name,
                    last_name=payload.last_name,
                    address=payload.address,
                    city=payload.city,
                    state=payload.state,
                    zipcode=payload.zipcode,
                    phone_number=payload.phone_number,
                )
            )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="email already exists") from exc
    return {"status": "created", "email": payload.email}
