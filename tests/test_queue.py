"""Тесты логики очереди."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.core.queue import (
    cache_result,
    cancel_task,
    create_task,
    get_cached_result,
    get_task,
    list_tasks,
    check_rate_limit_api,
    update_task_status,
)
from app.models.task import TaskStatus


@pytest.mark.asyncio
async def test_create_task_success(
    mock_session: AsyncMock,
    mock_redis_client: AsyncMock,
    mock_rabbit_client: AsyncMock,
) -> None:
    """Тест успешного создания задачи."""
    mock_task = MagicMock()
    mock_task.id = "new-task"  # uuid.uuid4().hex[:8] -> "new-task"
    mock_task.type = "send_email"
    mock_task.status = "pending"
    mock_task.retries = 0
    mock_task.max_retries = 3

    mock_session.add = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_task)

    mock_rabbit_client.channel = MagicMock()
    mock_rabbit_client.channel.is_closed = False
    mock_rabbit_client.channel.get_exchange = AsyncMock()

    # Замок broker.kick (вместо rabbit_client.publish)
    mock_broker = MagicMock()
    mock_process_task = MagicMock()
    mock_process_task.kiq = AsyncMock()
    mock_broker.write_conn = MagicMock()
    mock_broker.write_conn.is_closed = False

    with (
        patch("app.core.queue.get_session", return_value=mock_session),
        patch("app.core.queue.redis_client", mock_redis_client),
        patch("app.core.queue.rabbit_client", mock_rabbit_client),
        patch("app.core.queue.uuid.uuid4") as mock_uuid4,
        patch("app.tasks.worker.broker", mock_broker),
        patch("app.tasks.worker.process_task", mock_process_task),
    ):
        # uuid.uuid4().hex[:8] -> первые 8 символов
        mock_uuid4.return_value.hex = "new-task-xxxx"
        task = await create_task("send_email", {"to": "test@example.com"})

    assert task.id == "new-task"
    assert task.type == "send_email"
    mock_process_task.kiq.assert_called_once()


@pytest.mark.asyncio
async def test_create_task_invalid_type(
    mock_session: AsyncMock,
    mock_redis_client: AsyncMock,
    mock_rabbit_client: AsyncMock,
) -> None:
    """Тест создания задачи с невалидным типом."""
    with (
        patch("app.core.queue.get_session", return_value=mock_session),
        patch("app.core.queue.redis_client", mock_redis_client),
        patch("app.core.queue.rabbit_client", mock_rabbit_client),
    ):
        with pytest.raises(ValueError, match="Unknown task type"):
            await create_task("invalid_type", {})


@pytest.mark.asyncio
async def test_get_task_found(mock_session: AsyncMock) -> None:
    """Тест получения существующей задачи."""
    mock_task = MagicMock()
    mock_task.id = "test-id"
    mock_session.get.return_value = mock_task

    with patch("app.core.queue.get_session", return_value=mock_session):
        task = await get_task("test-id")

    assert task is not None
    assert task.id == "test-id"


@pytest.mark.asyncio
async def test_get_task_not_found(mock_session: AsyncMock) -> None:
    """Тест получения несуществующей задачи."""
    mock_session.get.return_value = None

    with patch("app.core.queue.get_session", return_value=mock_session):
        task = await get_task("nonexistent")

    assert task is None


@pytest.mark.asyncio
async def test_list_tasks(mock_session: AsyncMock) -> None:
    """Тест получения списка задач."""
    mock_tasks = [MagicMock() for _ in range(3)]
    for t in mock_tasks:
        t.id = f"task-{mock_tasks.index(t)}"

    mock_result = MagicMock()
    mock_result.scalars().all.return_value = mock_tasks

    mock_count = MagicMock()
    mock_count.scalar_one.return_value = 3

    async def execute_side_effect(*args: Any, **kwargs: Any) -> MagicMock:
        stmt = str(args[0]) if args else ""
        if "count" in stmt.lower() or "Count" in stmt:
            return mock_count
        return mock_result

    mock_session.execute.side_effect = execute_side_effect

    with patch("app.core.queue.get_session", return_value=mock_session):
        tasks, total = await list_tasks()

    assert len(tasks) == 3
    assert total == 3


@pytest.mark.asyncio
async def test_cancel_task_success(mock_session: AsyncMock) -> None:
    """Тест успешной отмены задачи."""
    mock_task = MagicMock()
    mock_task.id = "cancel-id"
    mock_task.status = "pending"
    mock_session.get.return_value = mock_task

    with patch("app.core.queue.get_session", return_value=mock_session):
        task = await cancel_task("cancel-id")

    assert task is not None
    assert task.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_task_not_found(mock_session: AsyncMock) -> None:
    """Тест отмены несуществующей задачи."""
    mock_session.get.return_value = None

    with patch("app.core.queue.get_session", return_value=mock_session):
        task = await cancel_task("nonexistent")

    assert task is None


@pytest.mark.asyncio
async def test_cancel_task_already_completed(mock_session: AsyncMock) -> None:
    """Тест отмены уже завершённой задачи."""
    mock_task = MagicMock()
    mock_task.id = "done-id"
    mock_task.status = TaskStatus.COMPLETED
    mock_session.get.return_value = mock_task

    with patch("app.core.queue.get_session", return_value=mock_session):
        with pytest.raises(ValueError, match="already completed"):
            await cancel_task("done-id")


@pytest.mark.asyncio
async def test_update_task_status(mock_session: AsyncMock) -> None:
    """Тест обновления статуса задачи."""
    mock_task = MagicMock()
    mock_task.id = "task-id"
    mock_session.get.return_value = mock_task

    with patch("app.core.queue.get_session", return_value=mock_session):
        await update_task_status("task-id", TaskStatus.COMPLETED, result={"ok": True})

    assert mock_task.status == TaskStatus.COMPLETED
    assert mock_task.result == {"ok": True}
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_cache_result(mock_redis_client: AsyncMock) -> None:
    """Тест кэширования результата."""
    with patch("app.core.queue.redis_client", mock_redis_client):
        await cache_result("task-id", {"ok": True})

    mock_redis_client.cache_set.assert_called_once()


@pytest.mark.asyncio
async def test_get_cached_result_found(mock_redis_client: AsyncMock) -> None:
    """Тест получения кэшированного результата."""
    mock_redis_client.cache_get.return_value = {"ok": True}

    with patch("app.core.queue.redis_client", mock_redis_client):
        result = await get_cached_result("task-id")

    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_get_cached_result_not_found(mock_redis_client: AsyncMock) -> None:
    """Тест получения отсутствующего кэша."""
    mock_redis_client.cache_get.return_value = None

    with patch("app.core.queue.redis_client", mock_redis_client):
        result = await get_cached_result("nonexistent")

    assert result is None


@pytest.mark.asyncio
async def test_check_rate_limit_allowed(mock_redis_client: AsyncMock) -> None:
    """Тест проверки rate limit (разрешено)."""
    mock_redis_client.check_rate_limit.return_value = (True, 50)

    with patch("app.core.queue.redis_client", mock_redis_client):
        allowed = await check_rate_limit_api()

    assert allowed is True


@pytest.mark.asyncio
async def test_check_rate_limit_denied(mock_redis_client: AsyncMock) -> None:
    """Тест проверки rate limit (запрещено)."""
    mock_redis_client.check_rate_limit.return_value = (False, 150)

    with patch("app.core.queue.redis_client", mock_redis_client):
        allowed = await check_rate_limit_api()

    assert allowed is False
