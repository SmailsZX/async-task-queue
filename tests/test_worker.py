"""Тесты воркера и обработчиков задач."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.config import settings
from app.tasks.handlers import send_email, process_data, generate_report, get_handler
from app.tasks.worker import process_task, AttemptMiddleware, DeadLetterMiddleware


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_email_success() -> None:
    """Тест успешной отправки email."""
    result = await send_email({"to": "test@example.com", "subject": "Test"})
    assert result["ok"] is True
    assert result["type"] == "send_email"
    assert result["to"] == "test@example.com"


@pytest.mark.asyncio
async def test_send_email_fail() -> None:
    """Тест ошибки при отправке email."""
    with pytest.raises(RuntimeError, match="Failed to send email"):
        await send_email({"to": "test@example.com", "fail": True})


@pytest.mark.asyncio
async def test_process_data_success() -> None:
    """Тест успешной обработки данных."""
    result = await process_data({"data": ["a", "b", "c"]})
    assert result["ok"] is True
    assert result["count"] == 3
    assert result["processed"] == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_process_data_fail() -> None:
    """Тест ошибки при обработке данных."""
    with pytest.raises(RuntimeError, match="Failed to process data"):
        await process_data({"data": [], "fail": True})


@pytest.mark.asyncio
async def test_generate_report_success() -> None:
    """Тест успешной генерации отчёта."""
    result = await generate_report({"report_type": "csv"})
    assert result["ok"] is True
    assert result["report_type"] == "csv"
    assert "report_id" in result


@pytest.mark.asyncio
async def test_generate_report_fail() -> None:
    """Тест ошибки при генерации отчёта."""
    with pytest.raises(RuntimeError, match="Failed to generate csv report"):
        await generate_report({"report_type": "csv", "fail": True})


def test_get_handler_valid() -> None:
    """Тест получения валидного handler."""
    handler = get_handler("send_email")
    assert callable(handler)


def test_get_handler_invalid() -> None:
    """Тест получения невалидного handler."""
    with pytest.raises(KeyError, match="Unknown task type"):
        get_handler("unknown_type")


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_task_success() -> None:
    """Тест успешного выполнения задачи."""
    mock_task = MagicMock()
    mock_task.id = "task-1"
    mock_task.type = "send_email"
    mock_task.payload = {"to": "test@example.com"}
    mock_task.retries = 0
    mock_task.max_retries = 3

    mock_session = AsyncMock()
    mock_session.get.return_value = mock_task
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.tasks.worker.get_session", return_value=mock_session),
        patch("app.tasks.worker.get_handler", return_value=send_email),
        patch("app.tasks.worker.update_task_status", new=AsyncMock()),
        patch("app.tasks.worker.cache_result", new=AsyncMock()),
    ):
        result = await process_task("task-1")

    assert result["ok"] is True
    assert result["type"] == "send_email"


@pytest.mark.asyncio
async def test_process_task_not_found() -> None:
    """Тест задачи, которой нет в БД."""
    mock_session = AsyncMock()
    mock_session.get.return_value = None
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.tasks.worker.get_session", return_value=mock_session),
        patch("app.tasks.worker.update_task_status", new=AsyncMock()),
    ):
        result = await process_task("nonexistent")

    assert result["error"] == "task_not_found"


@pytest.mark.asyncio
async def test_process_task_handler_error() -> None:
    """Тест ошибки в handler."""
    mock_task = MagicMock()
    mock_task.id = "task-2"
    mock_task.type = "process_data"
    mock_task.payload = {"fail": True}
    mock_task.retries = 0
    mock_task.max_retries = 3

    mock_session = AsyncMock()
    mock_session.get.return_value = mock_task
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.tasks.worker.get_session", return_value=mock_session),
        patch("app.tasks.worker.get_handler", return_value=process_data),
        patch("app.tasks.worker.update_task_status", new=AsyncMock()),
    ):
        result = await process_task("task-2")

    assert "error" in result
    mock_task.retries == 1


@pytest.mark.asyncio
async def test_process_task_timeout() -> None:
    """Тест таймаута задачи."""
    mock_task = MagicMock()
    mock_task.id = "task-3"
    mock_task.type = "generate_report"
    mock_task.payload = {"delay": 100}
    mock_task.retries = 0
    mock_task.max_retries = 3

    mock_session = AsyncMock()
    mock_session.get.return_value = mock_task
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    async def slow_handler(payload: dict) -> dict:
        import asyncio
        await asyncio.sleep(100)
        return {"ok": True}

    with (
        patch("app.tasks.worker.get_session", return_value=mock_session),
        patch("app.tasks.worker.get_handler", return_value=slow_handler),
        patch("app.tasks.worker.update_task_status", new=AsyncMock()),
        patch.object(settings.task, "task_timeout", 0.001),
    ):
        result = await process_task("task-3")

    assert result["error"] == "timeout"


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_attempt_middleware_pre_send() -> None:
    """Тест middleware для подсчёта попыток."""
    middleware = AttemptMiddleware()
    message = MagicMock()
    message.labels = {}

    result = await middleware.pre_send(message)

    assert result.labels["attempts"] == 1
    assert result.labels["max_retries"] == 3


@pytest.mark.asyncio
async def test_attempt_middleware_increments() -> None:
    """Тест инкремента attempts."""
    middleware = AttemptMiddleware()
    message = MagicMock()
    message.labels = {"attempts": 2}

    result = await middleware.pre_send(message)

    assert result.labels["attempts"] == 3


@pytest.mark.asyncio
async def test_dead_letter_middleware_no_retry() -> None:
    """Тест DLQ middleware — недостаточно попыток."""
    middleware = DeadLetterMiddleware()
    message = MagicMock()
    message.message_id = "msg-1"
    message.labels = {"attempts": 1, "max_retries": 3}

    result = await middleware.on_error(message, RuntimeError("test"))

    assert result.message_id == "msg-1"


@pytest.mark.asyncio
async def test_dead_letter_middleware_exhausted() -> None:
    """Тест DLQ middleware — попытки исчерпаны."""
    middleware = DeadLetterMiddleware()
    message = MagicMock()
    message.message_id = "msg-2"
    message.labels = {"attempts": 3, "max_retries": 3}

    result = await middleware.on_error(message, RuntimeError("final error"))

    assert result.message_id == "msg-2"
