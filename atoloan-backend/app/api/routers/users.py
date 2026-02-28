"""
User management endpoints.
"""
import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from app.db import get_engine
from app.models.user_create import UserCreate
from app.models.user_table import user_table

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


@router.post("")
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
