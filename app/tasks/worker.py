"""Taskiq-воркер: запуск обработчиков задач с retry и dead-letter.

Поток выполнения для process_task(task_id):
  1. Находит задачу в БД по task_id.
  2. Если задача не найдена — статус FAILED, возвращает ошибку.
  3. Определяет handler по task.type через get_handler().
  4. Вызывает handler(payload) с таймаутом asyncio.wait_for(...).
  5. При успехе → COMPLETED + кэширует результат в Redis.
  6. При ошибке → FAILED + инкрементирует retries.
  7. Если retries >= max_retries → задача уходит в dead-letter queue (через middleware).
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any

from taskiq import TaskiqMessage
from taskiq.abc.middleware import TaskiqMiddleware
from taskiq.events import TaskiqEvents
from taskiq_aio_pika import AioPikaBroker

from app.config import settings
from app.core.queue import cache_result, update_task_status
from app.core.redis import redis_client
from app.db import get_session
from app.models.task import Task, TaskStatus
from app.tasks.handlers import get_handler
from app.utils.logger import get_logger
from app.utils.metrics import TASKS_DURATION_SECONDS, TASKS_RETRY_TOTAL, TASKS_TOTAL

log = get_logger("worker")


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class AttemptMiddleware(TaskiqMiddleware):
    """Увеличивает счётчик попыток на 1 при отправке сообщения."""

    async def pre_send(self, message: TaskiqMessage) -> TaskiqMessage:
        attempts = int(message.labels.get("attempts", 0))
        message.labels["attempts"] = attempts + 1
        message.labels["max_retries"] = settings.task.max_retries
        return message


class DeadLetterMiddleware(TaskiqMiddleware):
    """При достижении max_retries перекидывает задачу в DLQ.

    Taskiq обрабатывает retry самостоятельно, поэтому middleware
    здесь только для логирования момента перехода в DLQ.
    """

    async def on_error(self, message: TaskiqMessage, error: Exception) -> TaskiqMessage:
        attempts = int(message.labels.get("attempts", 0))
        max_retries = int(message.labels.get("max_retries", 3))
        if attempts >= max_retries:
            log.warning(
                "task_sent_to_dlq",
                task_id=message.message_id,
                attempts=attempts,
                max_retries=max_retries,
            )
        return message


# ---------------------------------------------------------------------------
# Broker — единственное место создания
# ---------------------------------------------------------------------------

broker = AioPikaBroker(
    settings.rabbitmq.url,
).with_middlewares(
    AttemptMiddleware(),
    DeadLetterMiddleware(),
)


# ---------------------------------------------------------------------------
# Worker lifecycle: connect/disconnect Redis и broker
# ---------------------------------------------------------------------------

@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def worker_startup(state: dict[str, Any]) -> None:
    """Подключение Redis при старте воркера."""
    await redis_client.connect()
    log.info("worker_startup_complete")


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def worker_shutdown(state: dict[str, Any]) -> None:
    """Отключение Redis при остановке воркера."""
    await redis_client.close()
    log.info("worker_shutdown_complete")


# ---------------------------------------------------------------------------
# Задачи воркера
# ---------------------------------------------------------------------------

@broker.task(retry_on_error=True, max_retries=settings.task.max_retries)
async def process_task(task_id: str) -> dict[str, Any]:
    """Обработчик задачи воркера.

    Flow:
      1. Найти задачу в БД.
      2. Найти handler по типу.
      3. Выполнить с таймаутом.
      4. Обновить статус и кэш.
    """
    start_time = asyncio.get_event_loop().time()

    # 1. Найти задачу в БД
    async with get_session() as session:
        task = await session.get(Task, task_id)

    if task is None:
        log.error("task_not_found_in_db", task_id=task_id)
        await update_task_status(task_id, TaskStatus.FAILED, error="task_not_found")
        return {"error": "task_not_found", "task_id": task_id}

    # Помечаем статус как PROCESSING
    task.status = TaskStatus.PROCESSING
    task.started_at = datetime.datetime.now(datetime.timezone.utc)
    await update_task_status(task.id, TaskStatus.PROCESSING)

    # 2. Найти handler
    try:
        handler = get_handler(task.type)
    except KeyError as e:
        log.error("unknown_task_type", task_id=task_id, type=task.type)
        await update_task_status(task_id, TaskStatus.FAILED, error=str(e))
        return {"error": "unknown_task_type", "task_id": task_id}

    # 3. Выполнить handler с таймаутом
    payload = task.payload or {}
    try:
        result = await asyncio.wait_for(
            handler(payload),
            timeout=settings.task.task_timeout,
        )
    except asyncio.TimeoutError:
        log.error("task_timeout", task_id=task_id, timeout=settings.task.task_timeout)
        await update_task_status(task_id, TaskStatus.FAILED, error="timeout")
        TASKS_RETRY_TOTAL.labels(task_type=task.type).inc()
        return {"error": "timeout", "task_id": task_id, "type": task.type}
    except Exception as e:
        log.error("task_handler_error", task_id=task_id, error=str(e)[:200])
        # Инкрементируем попытки и сохраняем ошибку
        task.retries += 1
        await update_task_status(
            task_id,
            TaskStatus.FAILED,
            error=str(e),
        )
        TASKS_RETRY_TOTAL.labels(task_type=task.type).inc()
        TASKS_TOTAL.labels(task_type=task.type, status="failed").inc()

        # Если исчерпали max_retries — middleware отправит в DLQ
        if task.retries >= task.max_retries:
            log.warning("task_sent_to_dlq", task_id=task_id, retries=task.retries)
        return {"error": str(e), "task_id": task_id, "type": task.type}

    # 4. Успешное выполнение
    elapsed = asyncio.get_event_loop().time() - start_time
    TASKS_DURATION_SECONDS.labels(task_type=task.type).observe(elapsed)
    TASKS_TOTAL.labels(task_type=task.type, status="completed").inc()

    # Обновляем статус и кэшируем результат
    await update_task_status(task_id, TaskStatus.COMPLETED, result=result)
    await cache_result(task_id, result)

    log.info(
        "task_completed",
        task_id=task_id,
        type=task.type,
        elapsed=f"{elapsed:.2f}s",
    )
    return result


# ---------------------------------------------------------------------------
# Экспорт
# ---------------------------------------------------------------------------

__all__ = ["broker", "process_task"]
