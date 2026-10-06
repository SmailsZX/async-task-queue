"""Фабрика engine и сессий SQLAlchemy 2.0 (asyncpg)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.task import Base
from app.utils.logger import get_logger

log = get_logger("db")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Возвращает singleton AsyncEngine."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.postgres.url,
            pool_size=settings.postgres.pool_size,
            max_overflow=settings.postgres.max_overflow,
            pool_timeout=settings.postgres.pool_timeout,
            pool_recycle=settings.postgres.pool_recycle,
            pool_pre_ping=True,
            echo=settings.debug,
        )
        log.info("db_engine_created", url=settings.postgres.url)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Возвращает фабрику сессий."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Контекстный менеджер сессии БД."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def init_db() -> None:
    """Создаёт таблицы (для разработки; в проде — Alembic)."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("db_tables_created")


async def dispose_db() -> None:
    """Закрывает пул соединений."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        log.info("db_engine_disposed")


__all__ = [
    "get_engine",
    "get_session_factory",
    "get_session",
    "init_db",
    "dispose_db",
]