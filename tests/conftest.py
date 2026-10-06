"""Фикстуры для тестов."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.config import settings


@pytest.fixture(scope="session")
def event_loop() -> AsyncGenerator[asyncio.AbstractEventLoop, None]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def mock_session() -> AsyncMock:
    """Мокированная сессия БД — корректный async context manager."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.get = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    yield session


@pytest_asyncio.fixture
async def mock_redis_client() -> AsyncMock:
    """Мокированный клиент Redis."""
    redis = AsyncMock()
    redis.ping = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    redis.rpush = AsyncMock()
    redis.blpop = AsyncMock(return_value=None)
    redis.llen = AsyncMock(return_value=0)
    redis.xadd = AsyncMock(return_value="0-0")
    redis.xread = AsyncMock(return_value=[])
    redis.xack = AsyncMock()
    redis.xgroup_create = AsyncMock()
    redis.aclose = AsyncMock()

    # RedisClient использует self._pool
    redis_client = MagicMock()
    redis_client._pool = redis
    redis_client.client = redis
    redis_client.connect = AsyncMock()
    redis_client.close = AsyncMock()
    redis_client.cache_get = redis.get
    redis_client.cache_set = redis.set
    redis_client.cache_delete = redis.delete
    redis_client.check_rate_limit = redis.incr
    redis_client.queue_push = redis.rpush
    redis_client.queue_pop = redis.blpop
    redis_client.queue_size = redis.llen
    yield redis_client


@pytest_asyncio.fixture
async def mock_rabbit_client() -> AsyncMock:
    """Мокированный клиент RabbitMQ."""
    rabbit = AsyncMock()
    rabbit.connect = AsyncMock()
    rabbit.close = AsyncMock()
    rabbit.publish = AsyncMock()
    rabbit.declare_queue = AsyncMock()
    rabbit.declare_exchange = AsyncMock()
    rabbit.bind_queue = AsyncMock()
    rabbit.consume = AsyncMock()
    rabbit.stop_consume = AsyncMock()

    rabbit_client = MagicMock()
    rabbit_client._connection = None
    mock_channel = MagicMock()
    mock_channel.is_closed = False
    mock_channel.get_exchange = AsyncMock(return_value=MagicMock())
    rabbit_client.channel = mock_channel
    rabbit_client.connect = rabbit.connect
    rabbit_client.close = rabbit.close
    rabbit_client.publish = rabbit.publish
    rabbit_client.declare_queue = rabbit.declare_queue
    rabbit_client.declare_exchange = rabbit.declare_exchange
    rabbit_client.bind_queue = rabbit.bind_queue
    rabbit_client.consume = rabbit.consume
    rabbit_client.stop_consume = rabbit.stop_consume
    yield rabbit_client


@pytest_asyncio.fixture
async def client(
    mock_session: AsyncMock,
    mock_redis_client: AsyncMock,
    mock_rabbit_client: AsyncMock,
) -> AsyncGenerator[TestClient, None]:
    """Test client with mocked dependencies."""
    with (
        patch("app.core.queue.get_session", return_value=mock_session),
        patch("app.core.redis.redis_client", mock_redis_client),
        patch("app.core.rabbit.rabbit_client", mock_rabbit_client),
        patch("app.db.get_session_factory", return_value=lambda: mock_session),
        patch("app.api.routes.check_rate_limit_api", return_value=True),
    ):
        from app.main import app
        yield TestClient(app)


@pytest_asyncio.fixture
async def sample_task(mock_session: AsyncMock) -> MagicMock:
    task = MagicMock()
    task.id = "test-task-id"
    task.type = "send_email"
    task.status = "pending"
    task.payload = {"to": "test@example.com", "subject": "Test"}
    task.result = None
    task.error = None
    task.retries = 0
    task.max_retries = 3
    task.created_at = datetime.now(timezone.utc)
    task.updated_at = datetime.now(timezone.utc)
    task.started_at = None
    task.finished_at = None
    mock_session.get.return_value = task
    yield task


@pytest_asyncio.fixture
async def sample_task_list(mock_session: AsyncMock) -> list[MagicMock]:
    tasks = []
    for i in range(5):
        task = MagicMock()
        task.id = f"task-{i}"
        task.type = "process_data"
        task.status = "completed" if i % 2 == 0 else "pending"
        task.payload = {"data": [f"item{i}"]}
        task.result = {"ok": True} if task.status == "completed" else None
        task.error = None
        task.retries = 0
        task.max_retries = 3
        task.created_at = datetime.now(timezone.utc)
        task.updated_at = datetime.now(timezone.utc)
        task.started_at = datetime.now(timezone.utc)
        task.finished_at = datetime.now(timezone.utc) if task.status == "completed" else None
        tasks.append(task)

    mock_result = MagicMock()
    mock_result.scalars().all.return_value = tasks

    mock_count = MagicMock()
    mock_count.scalar_one.return_value = len(tasks)

    # Порядок вызовов: сначала get (для списка), потом count
    async def execute_side_effect(*args, **kwargs):
        stmt = str(args[0]) if args else ""
        if "count" in stmt or "Count" in stmt:
            return mock_count
        return mock_result

    mock_session.execute.side_effect = execute_side_effect
    yield tasks
