"""
Database client — thin wrapper around psycopg async connection pool.

Returns a swap-ready DatabaseClient. When database_url is empty, returns
a NullDatabaseClient that raises on every operation — forcing early failure
rather than silent data loss.

Usage:
    async with get_db_client() as db:
        rows = await db.fetch("SELECT * FROM verdicts WHERE id = $1", id)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import structlog

from backend.core.config import settings

log = structlog.get_logger(__name__)

_pool = None


class DatabaseClient:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def fetch(self, query: str, *args: Any) -> list[dict]:
        async with self._conn.cursor() as cur:
            await cur.execute(query, args)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in await cur.fetchall()]

    async def fetchrow(self, query: str, *args: Any) -> dict | None:
        rows = await self.fetch(query, *args)
        return rows[0] if rows else None

    async def execute(self, query: str, *args: Any) -> None:
        async with self._conn.cursor() as cur:
            await cur.execute(query, args)


class NullDatabaseClient:
    """Returned when no database_url is configured. Fails loudly."""

    def _fail(self) -> None:
        raise RuntimeError("No database_url configured — set DATABASE_URL in environment")

    async def fetch(self, *_: Any, **__: Any) -> list:
        self._fail()
        return []

    async def fetchrow(self, *_: Any, **__: Any) -> None:
        self._fail()

    async def execute(self, *_: Any, **__: Any) -> None:
        self._fail()


@asynccontextmanager
async def get_db_client() -> AsyncIterator[DatabaseClient | NullDatabaseClient]:
    """Async context manager that yields a usable database client."""
    if not settings.database_url:
        yield NullDatabaseClient()
        return

    try:
        import psycopg
        async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
            yield DatabaseClient(conn)
    except ImportError:
        log.warning("psycopg_not_installed", hint="pip install psycopg[binary]")
        yield NullDatabaseClient()
