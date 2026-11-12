"""
FastAPI application entry point.
Registers all routers and handles startup / shutdown lifecycle.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.db import create_tables, test_connection
# Re-exported for test monkeypatching compatibility
from app.integrations.seven_hundred import SevenHundredCreditClient  # noqa: F401
from app.api.routers.credit_unions import router as credit_unions_router
from app.api.routers.credit_unions import update_router
from app.api.routers.customer_auth import router as customer_auth_router
from app.api.routers.customer_portal import router as customer_portal_router
from app.api.routers.customers_admin import router as customers_admin_router
from app.api.routers.documents import router as documents_router
from app.api.routers.findback import router as findback_router
from app.api.routers.health import router as health_router
from app.api.routers.loan_applications import router as loan_applications_router
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


_docs = settings.enable_docs
app = FastAPI(
    title="ATOLoan Backend",
    lifespan=lifespan,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,  # customer session cookie; origins stay an explicit list
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_PRIVATE_PREFIXES = ("/auth/", "/me")


@app.middleware("http")
async def customer_session_guards(request: Request, call_next):
    """CSRF guard for the customer cookie: browsers always send Origin on
    cross-origin writes, including form posts that skip the CORS preflight and
    that SameSite=Lax still allows from sibling subdomains. Server-to-server
    callers send no Origin and are unaffected. Session responses are never cached."""
    origin = request.headers.get("origin")
    if request.method in _UNSAFE_METHODS and origin is not None and origin not in settings.cors_origins_list:
        return JSONResponse({"detail": "cross-origin request blocked"}, status_code=403)
    response = await call_next(request)
    if request.url.path.startswith(_PRIVATE_PREFIXES):
        response.headers["Cache-Control"] = "no-store"
    return response

app.include_router(health_router)
app.include_router(customer_auth_router)
app.include_router(customer_portal_router)
app.include_router(customers_admin_router)
app.include_router(credit_unions_router)
app.include_router(update_router)
app.include_router(rate_sheets_router)
app.include_router(findback_router)
app.include_router(users_router)
app.include_router(documents_router)
app.include_router(loan_applications_router)
