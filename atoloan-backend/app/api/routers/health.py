"""
Health-check and utility endpoints.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.dependencies import get_conn
from app.db import test_connection

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/hello")
async def hello() -> dict:
    return {"message": "hello world"}


@router.get("/db-check")
async def db_check() -> dict:
    try:
        await test_connection()
    except Exception as exc:
        logger.exception("DB health check failed")
        raise HTTPException(status_code=500, detail="database connection failed") from exc
    return {"status": "ok"}


@router.post("/echo")
async def echo(request: Request) -> dict:
    payload = await request.json()
    logger.info("echo payload: %s", payload)
    return {"received": payload}
