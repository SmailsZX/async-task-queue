"""Тесты API-эндпоинтов."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas.task import TaskCreate


@pytest.mark.asyncio
async def test_create_task(
    client: TestClient,
    mock_session: AsyncMock,
    mock_redis_client: AsyncMock,
    mock_rabbit_client: AsyncMock,
) -> None:
    """Тест создания задачи."""
    mock_task = MagicMock()
    mock_task.id = "new-task-id"
    mock_task.status = "pending"
    mock_task.retries = 0

    mock_session.add = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_task)

    with (
        patch("app.api.routes.create_task", return_value=mock_task),
        patch("app.core.queue.get_session", return_value=mock_session),
        patch("app.core.redis.redis_client", mock_redis_client),
        patch("app.core.rabbit.rabbit_client", mock_rabbit_client),
    ):
        response = client.post(
            "/tasks",
            json={"type": "send_email", "payload": {"to": "test@example.com"}},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["id"] == "new-task-id"
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_create_task_rate_limit_exceeded(
    client: TestClient,
    mock_redis_client: AsyncMock,
) -> None:
    """Тест rate limit при превышении лимита."""
    mock_redis_client.check_rate_limit.return_value = (False, 101)

    with patch("app.api.routes.check_rate_limit_api", return_value=False):
        response = client.post(
            "/tasks",
            json={"type": "send_email", "payload": {}},
        )

    assert response.status_code == 429


@pytest.mark.asyncio
async def test_create_task_invalid_type(
    client: TestClient,
    mock_session: AsyncMock,
    mock_rabbit_client: AsyncMock,
) -> None:
    """Тест создания задачи с невалидным типом."""
    mock_task = MagicMock()
    mock_task.id = "new-task-id"
    mock_task.status = "pending"
    mock_task.retries = 0

    mock_session.get = AsyncMock(return_value=mock_task)

    with (
        patch("app.api.routes.create_task", side_effect=ValueError("Unknown task type")),
        patch("app.core.queue.get_session", return_value=mock_session),
        patch("app.core.rabbit.rabbit_client", mock_rabbit_client),
    ):
        response = client.post(
            "/tasks",
            json={"type": "invalid_type", "payload": {}},
        )

    assert response.status_code == 500


@pytest.mark.asyncio
async def test_get_task_found(
    client: TestClient,
    mock_session: AsyncMock,
    sample_task: MagicMock,
    mock_redis_client: AsyncMock,
    mock_rabbit_client: AsyncMock,
) -> None:
    """Тест получения существующей задачи."""
    from app.models.task import TaskStatus

    task = sample_task
    task.status = TaskStatus.COMPLETED
    task.result = {"ok": True, "type": "send_email"}
    mock_redis_client.cache_get.return_value = None

    with (
        patch("app.api.routes.get_task", return_value=task),
        patch("app.core.queue.redis_client", mock_redis_client),
        patch("app.core.rabbit.rabbit_client", mock_rabbit_client),
    ):
        response = client.get(f"/tasks/{task.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == task.id
    assert data["status"] == "completed"


@pytest.mark.asyncio
async def test_get_task_not_found(client: TestClient, mock_redis_client: AsyncMock) -> None:
    """Тест получения несуществующей задачи."""
    with (
        patch("app.api.routes.get_task", return_value=None),
        patch("app.core.queue.redis_client", mock_redis_client),
    ):
        mock_redis_client.cache_get.return_value = None
        response = client.get("/tasks/nonexistent-id")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_tasks(
    client: TestClient,
    mock_session: AsyncMock,
    sample_task_list: list[MagicMock],
) -> None:
    """Тест списка задач."""
    with patch("app.api.routes.list_tasks", return_value=(sample_task_list, 5)):
        response = client.get("/tasks")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5
    assert len(data["items"]) == 5


@pytest.mark.asyncio
async def test_cancel_task(
    client: TestClient,
    mock_session: AsyncMock,
    sample_task: MagicMock,
    mock_redis_client: AsyncMock,
    mock_rabbit_client: AsyncMock,
) -> None:
    """Тест отмены задачи."""
    task = sample_task
    task.status = "cancelled"  # after cancel_task
    mock_redis_client.cache_get.return_value = None

    with (
        patch("app.api.routes.cancel_task", return_value=task),
        patch("app.core.queue.redis_client", mock_redis_client),
        patch("app.core.rabbit.rabbit_client", mock_rabbit_client),
    ):
        response = client.delete(f"/tasks/{task.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_task_not_found(client: TestClient) -> None:
    """Тест отмены несуществующей задачи."""
    with patch("app.api.routes.cancel_task", return_value=None):
        response = client.delete("/tasks/nonexistent-id")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_health_check(client: TestClient) -> None:
    """Тест health check."""
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_metrics(client: TestClient) -> None:
    """Тест метрик Prometheus."""
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
