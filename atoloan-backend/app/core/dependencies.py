"""
Shared FastAPI dependency injections.
"""
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import get_engine


async def get_conn() -> AsyncGenerator[AsyncConnection, None]:
    """Yield a transactional async DB connection for use in route handlers."""
    async with get_engine().begin() as conn:
        yield conn
