import logging
from pathlib import Path
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Optional

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
from app.services.rate_sheet_parser import parse_rate_sheet_from_markdown
from app.services.credit_union_retrieval import (
    get_all_credit_unions,
    get_bank_info,
    get_rate_policy,
    get_loan_programs
)
from app.services.credit_union_mutations import (
    upsert_bank_info,
    upsert_rate_policy_items,
    upsert_loan_program_items
)
from app.services.credit_union_deletion import delete_credit_union_and_related
from app.services.bank_finder import find_best_bank


# Load environment variables from .env file
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    load_dotenv(env_file)
    print(f"[STARTUP] Loaded .env from: {env_file}")
else:
    # Try loading from project root
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        print(f"[STARTUP] Loaded .env from: {env_file}")
    else:
        print(f"[WARNING] No .env file found")

# Verify OPENAI_API_KEY is loaded
api_key = os.getenv("OPENAI_API_KEY")
if api_key:
    masked = api_key[:20] + "..." + api_key[-4:] if len(api_key) > 24 else "***"
    print(f"[STARTUP] ✓ OPENAI_API_KEY is set: {masked}")
else:
    print(f"[WARNING] OPENAI_API_KEY is not set in environment!")

logging.basicConfig(level=logging.INFO)

# Thread pool for running blocking operations
executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="parser_")


def parse_rate_sheet_sync(markdown_content: str) -> dict:
    """Synchronous wrapper for rate sheet parser that can be run in executor"""
    try:
        print(f"\n[ASYNC WORKER] Starting rate sheet parsing...")
        import sys
        sys.stdout.flush()
        
        result = parse_rate_sheet_from_markdown(markdown_content)
        print(result.loan_programs[0] if result and result.loan_programs else "No loan programs found")
        
        if result:
            print(f"[ASYNC WORKER] ✓ Parser completed successfully!")
            print(f"[ASYNC WORKER] Converting to dictionary...")
            sys.stdout.flush()
            
            result_dict = result.dict()
            
            # Print summary
            print(f"\n[ASYNC WORKER] 📊 PARSED RATE SHEET SUMMARY:")
            print(f"[ASYNC WORKER] " + "="*70)
            
            if result.credit_union_info:
                cu = result.credit_union_info
                print(f"[ASYNC WORKER] Credit Union: {cu.name}")
                print(f"[ASYNC WORKER] Effective Date: {cu.effective_date}")
                
            if result.loan_programs:
                print(f"[ASYNC WORKER] Loan Programs: {len(result.loan_programs)} found")
                for prog in result.loan_programs[:3]:
                    print(f"[ASYNC WORKER]   - {prog.program_name} ({prog.vehicle_type})")
                if len(result.loan_programs) > 3:
                    print(f"[ASYNC WORKER]   ... and {len(result.loan_programs) - 3} more")
                    
            if result.guidelines:
                print(f"[ASYNC WORKER] Guidelines: Income ≥ {result.guidelines.income_requirements}")
                
            if result.rate_policy:
                print(f"[ASYNC WORKER] Rate Policy: Base discount {result.rate_policy.base_discount}")
                
            print(f"[ASYNC WORKER] " + "="*70)
            sys.stdout.flush()
            
            return result_dict
        else:
            print(f"[ASYNC WORKER] ✗ Parser returned None")
            sys.stdout.flush()
            return None
    except Exception as e:
        print(f"[ASYNC WORKER] ✗ Exception: {e}")
        import traceback
        traceback.print_exc()
        import sys
        sys.stdout.flush()
        return None


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
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
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


@app.post("/update")
async def update(request: Request) -> dict:
    """
    Upsert rate sheet data into the database.

    Expects the parsed rate sheet JSON structure with:
    - credit_union_info
    - rate_policy
    - loan_programs
    - guidelines
    - special_programs
    - participation_and_funding
    - additional_details
    """
    payload = await request.json()
    print("\n" + "="*70)
    print("[UPDATE ENDPOINT] Received request:")
    print("="*70)
    print(f"Bank: {payload.get('credit_union_info', {}).get('name', 'Unknown')}")
    print("="*70 + "\n")
    logging.info("[UPDATE] Received payload for bank: %s", payload.get('credit_union_info', {}).get('name'))

    try:
        engine = get_engine()
        async with engine.begin() as conn:
            # Step 1: Upsert bank_info
            bank_id = await upsert_bank_info(conn, payload)
            print(f"[UPDATE] Upserted bank_info with ID: {bank_id}")

            # Step 2: Upsert rate_policy_items
            rate_policy_count = await upsert_rate_policy_items(conn, bank_id, payload)
            print(f"[UPDATE] Upserted {rate_policy_count} rate_policy_items")

            # Step 3: Upsert loan_program_items
            loan_program_count = await upsert_loan_program_items(conn, bank_id, payload)
            print(f"[UPDATE] Upserted {loan_program_count} loan_program_items")

            print("="*70)
            print(f"[UPDATE] ✓ Successfully upserted all data for bank ID {bank_id}")
            print("="*70 + "\n")

            return {
                "status": "success",
                "bank_id": bank_id,
                "rate_policy_items_count": rate_policy_count,
                "loan_program_items_count": loan_program_count
            }

    except Exception as e:
        logging.exception(f"[UPDATE] Failed to upsert data: {e}")
        raise HTTPException(status_code=500, detail=f"Database upsert failed: {str(e)}")


@app.get("/credit-unions")
async def get_credit_unions_endpoint() -> dict:
    """
    Get list of all credit unions.

    Returns:
        List of credit unions with their id and name
    """
    try:
        engine = get_engine()
        async with engine.begin() as conn:
            credit_unions = await get_all_credit_unions(conn)

            return {
                "status": "success",
                "credit_unions": credit_unions,
                "count": len(credit_unions)
            }

    except Exception as e:
        logging.exception(f"[GET CREDIT UNIONS] Failed to retrieve data: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve credit unions: {str(e)}")


@app.delete("/credit-unions/{bank_id}")
async def delete_credit_union(bank_id: int) -> dict:
    """
    Delete a credit union and all its related data.

    Deletes from:
    - loan_program_items (all programs, tiers, terms)
    - rate_policy_items (discounts, adjustments, fees)
    - bank_info (credit union information)

    Args:
        bank_id: The bank ID to delete

    Returns:
        Status of deletion with counts of deleted records
    """
    try:
        engine = get_engine()
        async with engine.begin() as conn:
            deleted = await delete_credit_union_and_related(conn, bank_id)

            return {
                "status": "success",
                "message": f"Credit union '{deleted['bank_name']}' deleted successfully",
                "deleted": deleted
            }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.exception(f"[DELETE] Failed to delete credit union: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete credit union: {str(e)}")


@app.get("/credit-unions/{bank_id}/ratesheet")
async def get_credit_union_ratesheet(bank_id: int) -> dict:
    """
    Get complete credit union rate sheet information including:
    - Credit union details
    - Rate policy (discounts, adjustments, fees)
    - All loan programs with tiers and terms

    Args:
        bank_id: The bank ID to retrieve

    Returns:
        Complete rate sheet data in structured format
    """
    try:
        engine = get_engine()
        async with engine.begin() as conn:
            # Step 1: Get bank info
            bank_info_data = await get_bank_info(conn, bank_id)
            if not bank_info_data:
                raise HTTPException(status_code=404, detail=f"Credit union with ID {bank_id} not found")

            # Step 2: Get rate policy items
            rate_policy_data = await get_rate_policy(conn, bank_id)

            # Step 3: Get loan programs with hierarchical structure
            loan_programs_data = await get_loan_programs(conn, bank_id)

            return {
                "bank_id": bank_id,
                "credit_union_info": bank_info_data["credit_union_info"],
                "rate_policy": rate_policy_data,
                "loan_programs": loan_programs_data,
                "guidelines": bank_info_data["guidelines"],
                "special_programs": bank_info_data["special_programs"],
                "participation_and_funding": bank_info_data["participation_and_funding"],
                "additional_details": bank_info_data["additional_details"]
            }

    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"[GET RATESHEET] Failed to retrieve data: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve rate sheet: {str(e)}")


@app.post("/findback")
async def findback(request: Request) -> dict:
    payload = await request.json()
    logging.info("findback payload: %s", payload)

    # Store original payload for later use
    original_payload = payload.copy() if isinstance(payload, dict) else {}

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

    # ========================================================================
    # BANK FINDER INTEGRATION
    # ========================================================================
    # After getting 700Credit response, find the best bank offer
    best_bank_offer = None
    bank_finder_error = None

    try:
        # Extract required parameters for bank finder
        zipcode = payload["zip_code"]

        # Get down_payment from original payload
        # First check if user entered a custom value in otherDownPayment
        down_payment = original_payload.get("otherDownPayment")

        # If no custom value, get from answers object and parse the range
        if not down_payment:
            answers = original_payload.get("answers", {})
            down_payment_range = answers.get("down-payment")

            if down_payment_range:
                # Parse range like "5000-6500" to get the midpoint
                try:
                    if "-" in str(down_payment_range):
                        parts = str(down_payment_range).split("-")
                        min_val = float(parts[0].strip())
                        max_val = float(parts[1].strip())
                        down_payment = (min_val + max_val) / 2  # Use midpoint
                        logging.info(f"[BANK FINDER] Parsed down payment range '{down_payment_range}' to ${down_payment}")
                    else:
                        # Single value, not a range
                        down_payment = float(down_payment_range)
                except (ValueError, IndexError) as e:
                    logging.warning(f"[BANK FINDER] Could not parse down_payment range '{down_payment_range}': {e}")
                    down_payment = None
        else:
            # Convert custom down payment to float
            try:
                down_payment = float(down_payment)
            except (ValueError, TypeError):
                logging.warning(f"[BANK FINDER] Invalid otherDownPayment value: {down_payment}")
                down_payment = None

        # Extract credit score from 700Credit response
        # The credit score is typically in the prequal response
        prequal_data = result.to_dict()
        credit_score = 740

        # Try to find credit score in the response structure
        # Common locations: prequal_data.get("credit_score") or prequal_data.get("score")
        # if isinstance(prequal_data, dict):
            # credit_score = (
            #     prequal_data.get("credit_score") or
            #     prequal_data.get("score") or
            #     prequal_data.get("fico_score")
            # )

            # # Sometimes credit score is nested in a bureau response
            # if not credit_score and "bureau_response" in prequal_data:
            #     bureau_data = prequal_data.get("bureau_response", {})
            #     if isinstance(bureau_data, dict):
            #         credit_score = (
            #             bureau_data.get("credit_score") or
            #             bureau_data.get("score") or
            #             bureau_data.get("fico_score")
            #         )

        # Only run bank finder if we have all required parameters
        if down_payment and credit_score and zipcode:
            logging.info(
                f"[BANK FINDER] Running with zipcode={zipcode}, "
                f"down_payment={down_payment}, credit_score={credit_score}"
            )

            engine = get_engine()
            async with engine.begin() as conn:
                best_bank_offer = await find_best_bank(
                    conn,
                    zipcode=str(zipcode),
                    down_payment=float(down_payment),
                    credit_score=int(credit_score)
                )

            if best_bank_offer:
                logging.info(
                    f"[BANK FINDER] Found best offer: {best_bank_offer['bank_name']} "
                    f"at {best_bank_offer['interest_rate']}"
                )
            else:
                logging.warning("[BANK FINDER] No eligible banks found for user criteria")
        else:
            missing_params = []
            if not down_payment:
                missing_params.append("down_payment")
            if not credit_score:
                missing_params.append("credit_score (from 700Credit response)")
            if not zipcode:
                missing_params.append("zipcode")

            logging.warning(
                f"[BANK FINDER] Skipped - missing parameters: {', '.join(missing_params)}"
            )
            bank_finder_error = f"Missing required parameters: {', '.join(missing_params)}"

    except Exception as e:
        logging.exception(f"[BANK FINDER] Error finding best bank: {e}")
        bank_finder_error = str(e)

    # Add bank finder results to response
    if best_bank_offer:
        response["best_bank"] = best_bank_offer

    if bank_finder_error:
        response["bank_finder_error"] = bank_finder_error

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
    print(f"\n[DEBUG] ratesheetuploader endpoint called")
    content_type = request.headers.get("content-type", "")
    print(f"[DEBUG] content_type: {content_type}")
    
    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        print(f"[DEBUG] Processing multipart/form-data request")
        form = await request.form()
        print(f"[DEBUG] Form received with items")
        data = {}
        files = []
        upload_dir = Path("upload_pdf")
        upload_dir.mkdir(parents=True, exist_ok=True)
        
        for key, value in form.multi_items():
            print(f"[DEBUG] Processing form item: key={key}, has_filename={hasattr(value, 'filename')}")
            
            if hasattr(value, "filename"):
                filename = Path(value.filename).name
                print(f"[DEBUG] File uploaded: {filename}")
                target = upload_dir / filename
                content = await value.read()
                target.write_bytes(content)
                print(f"[DEBUG] File saved to: {target}")
                
                parsed = None
                parse_error = None
                validation = None
                
                if value.content_type == "application/pdf" or filename.lower().endswith(".pdf"):
                    print(f"[DEBUG] Processing as PDF: content_type={value.content_type}")
                    try:
                        # Parse PDF with improved parser
                        print(f"[DEBUG] Calling parse_pdf...")
                        parsed = parse_pdf(target)
                        print(f"[DEBUG] parse_pdf returned: {type(parsed)}")
                        print(f"[DEBUG] parsed keys: {parsed.keys() if isinstance(parsed, dict) else 'not a dict'}")
                        
                        # Optional: Validate the generated markdown
                        try:
                            markdown_path = Path(parsed.get("markdown_path"))
                            print(f"\n[DEBUG] markdown_path: {markdown_path}")
                            print(f"[DEBUG] markdown_path exists: {Path(markdown_path).exists()}")
                            
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
                            
                            # Parse rate sheet from markdown
                            if markdown_path and Path(markdown_path).exists():
                                try:
                                    print(f"\n[DEBUG] Reading markdown file from: {markdown_path}")
                                    markdown_content = Path(markdown_path).read_text(encoding="utf-8")
                                    print(f"[DEBUG] Markdown content length: {len(markdown_content)} chars")
                                    print(f"[DEBUG] About to call LLM parser (no timeout)...")
                                    import sys
                                    sys.stdout.flush()

                                    # Run parser directly (it's blocking but we'll handle it)
                                    # Create a task and await it without timeout
                                    import concurrent.futures
                                    loop = asyncio.get_event_loop()
                                    future = loop.run_in_executor(executor, parse_rate_sheet_sync, markdown_content)

                                    print(f"[DEBUG] Waiting for parser result (no timeout)...")
                                    sys.stdout.flush()

                                    # Await the future without timeout
                                    rate_sheet_dict = await future

                                    print(f"[DEBUG] Parser result received!")
                                    sys.stdout.flush()

                                    if rate_sheet_dict:
                                        parsed["rate_sheet_parsed"] = rate_sheet_dict
                                        logging.info(f"Successfully parsed rate sheet from {filename}")
                                        print("\n" + "="*80)
                                        print(f"✓ RATE SHEET SUCCESSFULLY PARSED FROM {filename}:")
                                        print("="*80)
                                        import json
                                        print(json.dumps(rate_sheet_dict, indent=2, default=str)[:500] + "...")
                                        print("="*80 + "\n")
                                    else:
                                        print(f"\n[ERROR] Parser returned None")
                                        logging.warning(f"Failed to parse rate sheet from {filename}")
                                except Exception as rate_exc:
                                    print(f"\n[ERROR] Exception during rate sheet parsing: {rate_exc}")
                                    print(f"[ERROR] Exception type: {type(rate_exc).__name__}")
                                    import traceback
                                    traceback.print_exc()
                                    import sys
                                    sys.stdout.flush()
                                    logging.warning(f"Rate sheet parsing failed for {filename}: {rate_exc}")
                            else:
                                print(f"\n[WARNING] Markdown file not found or path is empty: {markdown_path}")
                                import sys
                                sys.stdout.flush()
                        except Exception as val_exc:
                            print(f"\n[ERROR] PDF validation failed: {val_exc}")
                            logging.warning(f"PDF validation failed for {filename}: {val_exc}")
                            validation = {"error": str(val_exc)}
                            
                    except Exception as exc:
                        parse_error = str(exc)
                        print(f"[ERROR] PDF parsing failed: {exc}")
                        logging.exception("ratesheetuploader pdf parse failed")
                        
                logging.info("ratesheetuploader parsed: %s", parsed)
                
                # Extract rate sheet parsed data if available
                rate_sheet_data = None
                if isinstance(parsed, dict) and "rate_sheet_parsed" in parsed:
                    rate_sheet_data = parsed.get("rate_sheet_parsed")
                
                files.append(
                    {
                        "filename": filename,
                        "parse_error": parse_error,
                        "validation": validation,
                        "rate_sheet": rate_sheet_data,
                    }
                )
            else:
                data.setdefault(key, []).append(value)
        print(f"[DEBUG] Processing complete. Total files: {len(files)}")
        logging.info("ratesheetuploader form fields: %s", data)
        logging.info("ratesheetuploader files: %s", files)
        return {"status": "ok", "fields": data, "files": files}

    print(f"[DEBUG] Not multipart - reading raw body")
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


@app.post("/parse-rate-sheet-markdown")
async def parse_rate_sheet_markdown(request: Request) -> dict:
    """
    Parse markdown text from a rate sheet and extract structured data.
    
    Expects JSON payload with:
    {
        "markdown_text": "The markdown content from rate sheet...",
        "current_year": 2025  # optional, defaults to 2025
    }
    
    Returns:
    {
        "status": "success" | "error",
        "result": CreditUnionRateSheet object (if successful),
        "error": error message (if failed)
    }
    """
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON payload"
        ) from e

    # Validate required field
    markdown_text = payload.get("markdown_text")
    if not markdown_text or not isinstance(markdown_text, str):
        raise HTTPException(
            status_code=400,
            detail="markdown_text is required and must be a non-empty string"
        )

    current_year = payload.get("current_year", 2025)
    if not isinstance(current_year, int) or current_year < 1900 or current_year > 2100:
        raise HTTPException(
            status_code=400,
            detail="current_year must be a valid integer between 1900 and 2100"
        )

    try:
        logging.info("Parsing rate sheet markdown...")
        rate_sheet = parse_rate_sheet_from_markdown(markdown_text, current_year=current_year)

        if rate_sheet is None:
            return {
                "status": "error",
                "error": "Failed to parse rate sheet. The markdown content may be invalid or incomplete."
            }

        return {
            "status": "success",
            "result": rate_sheet.dict()
        }

    except Exception as e:
        logging.exception("Rate sheet markdown parsing failed")
        raise HTTPException(
            status_code=500,
            detail=f"Rate sheet parsing failed: {str(e)}"
        ) from e


@app.post("/uploadDocuments")
async def upload_documents(request: Request) -> dict:
    """
    Upload user documents (driver's license and paycheck) for loan application.
    
    Accepts multipart/form-data with:
    - drivers_license: Image file of driver's license
    - paycheck: Image/PDF file of paycheck/pay stub
    - user_email: (optional) User's email for organizing files
    - user_name: (optional) User's name for organizing files
    
    Files are saved to user_uploaded_documents directory.
    """
    content_type = request.headers.get("content-type", "")
    
    if "multipart/form-data" not in content_type:
        raise HTTPException(
            status_code=400,
            detail="Content-Type must be multipart/form-data"
        )
    
    form = await request.form()
    
    # Create upload directory if it doesn't exist
    upload_dir = Path("user_uploaded_documents")
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    # Extract optional metadata
    user_email = form.get("user_email", "unknown")
    user_name = form.get("user_name", "unknown")
    
    # Create a timestamp-based subfolder for this submission
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c if c.isalnum() else "_" for c in str(user_name))
    submission_dir = upload_dir / f"{timestamp}_{safe_name}"
    submission_dir.mkdir(parents=True, exist_ok=True)
    
    uploaded_files = []
    errors = []
    
    # Process drivers_license
    drivers_license = form.get("drivers_license")
    if drivers_license and hasattr(drivers_license, "filename") and drivers_license.filename:
        try:
            filename = Path(drivers_license.filename).name
            # Sanitize filename
            safe_filename = f"drivers_license_{filename}"
            target_path = submission_dir / safe_filename
            content = await drivers_license.read()
            target_path.write_bytes(content)
            uploaded_files.append({
                "field": "drivers_license",
                "filename": safe_filename,
                "path": str(target_path),
                "size": len(content)
            })
            logging.info(f"[UPLOAD] Saved driver's license: {target_path}")
        except Exception as e:
            errors.append(f"Failed to save driver's license: {str(e)}")
            logging.exception("Failed to save driver's license")
    else:
        errors.append("drivers_license file is required")
    
    # Process paycheck
    paycheck = form.get("paycheck")
    if paycheck and hasattr(paycheck, "filename") and paycheck.filename:
        try:
            filename = Path(paycheck.filename).name
            # Sanitize filename
            safe_filename = f"paycheck_{filename}"
            target_path = submission_dir / safe_filename
            content = await paycheck.read()
            target_path.write_bytes(content)
            uploaded_files.append({
                "field": "paycheck",
                "filename": safe_filename,
                "path": str(target_path),
                "size": len(content)
            })
            logging.info(f"[UPLOAD] Saved paycheck: {target_path}")
        except Exception as e:
            errors.append(f"Failed to save paycheck: {str(e)}")
            logging.exception("Failed to save paycheck")
    else:
        errors.append("paycheck file is required")
    
    # Return response
    if len(uploaded_files) == 2:
        return {
            "status": "success",
            "message": "Documents uploaded successfully",
            "submission_id": f"{timestamp}_{safe_name}",
            "files": uploaded_files
        }
    elif uploaded_files:
        return {
            "status": "partial",
            "message": "Some documents uploaded",
            "submission_id": f"{timestamp}_{safe_name}",
            "files": uploaded_files,
            "errors": errors
        }
    else:
        raise HTTPException(
            status_code=400,
            detail=f"No documents uploaded: {'; '.join(errors)}"
        )
