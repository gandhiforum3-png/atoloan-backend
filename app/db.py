import getpass
import os
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.models.user_table import metadata

_engine: Optional[AsyncEngine] = None


def get_database_url(
    host: str | None = None,
    port: str | None = None,
    user: str | None = None,
    password: str | None = None,
    dbname: str | None = None,
) -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url

    resolved_host = host or os.getenv("PGHOST", "localhost")
    resolved_port = port or os.getenv("PGPORT", "5432")
    resolved_user = user or os.getenv("PGUSER") or getpass.getuser()
    resolved_password = password if password is not None else os.getenv("PGPASSWORD")
    resolved_dbname = dbname or os.getenv("PGDATABASE", "atoloan")

    try:
        port_value = int(resolved_port)
    except ValueError as exc:
        raise ValueError("PGPORT must be an integer") from exc

    return str(
        URL.create(
            "postgresql+asyncpg",
            username=resolved_user,
            password=resolved_password,
            host=resolved_host,
            port=port_value,
            database=resolved_dbname,
        )
    )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_database_url(), pool_pre_ping=True)
    return _engine


async def test_connection() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def create_tables() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
