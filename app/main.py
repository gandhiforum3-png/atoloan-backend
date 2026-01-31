import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError

from app.db import create_tables, get_engine, test_connection
from app.integrations.seven_hundred import SevenHundredCreditClient
from app.models.user_create import UserCreate
from app.models.user_table import user_table


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
    allow_origins=["http://localhost:5173"],
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
