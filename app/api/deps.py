"""Зависимости FastAPI."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory


async def get_db() -> AsyncSession:
    """Зависимость для получения сессии БД."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


__all__ = ["get_db"]
