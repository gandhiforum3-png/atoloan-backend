"""
FastAPI application entry point.
Registers all routers and handles startup / shutdown lifecycle.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.db import create_tables, test_connection
# Re-exported for test monkeypatching compatibility
from app.integrations.seven_hundred import SevenHundredCreditClient  # noqa: F401
from app.api.routers.credit_unions import router as credit_unions_router
from app.api.routers.credit_unions import update_router
from app.api.routers.documents import router as documents_router
from app.api.routers.findback import router as findback_router
from app.api.routers.health import router as health_router
from app.api.routers.rate_sheets import router as rate_sheets_router
from app.api.routers.users import router as users_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        await create_tables()
        await test_connection()
        logger.info("Database connection successful")
    except Exception:
        logger.exception("Database connection failed on startup")
    yield


app = FastAPI(title="ATOLoan Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(credit_unions_router)
app.include_router(update_router)
app.include_router(rate_sheets_router)
app.include_router(findback_router)
app.include_router(users_router)
app.include_router(documents_router)
