"""FastAPI приложение Async Task Queue."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import Response

from app.api.routes import router
from app.config import settings
from app.core.rabbit import rabbit_client
from app.core.redis import redis_client
from app.db import dispose_db, init_db
from app.utils.logger import configure_logging
from app.utils.metrics import APP_UP, metrics_response, content_type


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения."""
    # Запуск
    configure_logging()
    await redis_client.connect()
    await rabbit_client.connect()
    await init_db()
    # Запуск broker для отправки задач
    from app.tasks.worker import broker
    if not broker.write_conn or broker.write_conn.is_closed:
        await broker.startup()
    APP_UP.set(1)
    yield
    # Остановка
    APP_UP.set(0)
    await dispose_db()
    await redis_client.close()
    await rabbit_client.close()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": settings.app_version}


@app.get("/metrics")
async def metrics_endpoint():
    """Эндпоинт для Prometheus-метрик."""
    return Response(
        content=metrics_response(),
        media_type=content_type(),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=settings.debug)
