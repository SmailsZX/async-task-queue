"""Логика очереди: постановка задач, кэш, управление статусами в БД."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.rabbit import rabbit_client
from app.core.redis import redis_client
from app.db import get_session
from app.models.task import Task, TaskStatus
from app.utils.logger import get_logger
from app.utils.metrics import (
    APP_UP,
    RATE_LIMIT_HITS,
    TASKS_DURATION_SECONDS,
    TASKS_QUEUE_SIZE,
    TASKS_RETRY_TOTAL,
    TASKS_TOTAL,
)

log = get_logger("queue")

TASK_RESULT_PREFIX = "result:"
TASK_CACHE_TTL = settings.task.default_ttl
RATE_LIMIT_KEY = "rate_limit:api"


async def create_task(type_: str, payload: dict[str, Any] | None = None) -> Task:
    """Создаёт задачу в PostgreSQL и ставит в очередь RabbitMQ."""
    if type_ not in ("send_email", "process_data", "generate_report"):
        raise ValueError(f"Unknown task type: {type_}")

    task_id = uuid.uuid4().hex[:8]
    max_retries = settings.task.max_retries

    async with get_session() as session:
        task = Task(
            id=task_id,
            type=type_,
            status=TaskStatus.PENDING,
            payload=payload,
            max_retries=max_retries,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

    log.info("task_created", task_id=task_id, type=type_)

    # Отправляем задачу через Taskiq broker
    try:
        from app.tasks.worker import broker
        if not broker.write_conn or broker.write_conn.is_closed:
            await broker.startup()
        from app.tasks.worker import process_task
        await process_task.kiq(task_id)
        TASKS_QUEUE_SIZE.labels(queue="tasks").inc()
    except Exception:
        log.exception("broker_kick_failed", task_id=task_id)
        async with get_session() as session:
            t = await session.get(Task, task_id)
            if t is not None:
                t.status = TaskStatus.FAILED
                t.error = "broker_kick_failed"
                await session.commit()
        TASKS_TOTAL.labels(task_type=type_, status="failed").inc()
        raise

    TASKS_TOTAL.labels(task_type=type_, status="pending").inc()
    return task


async def get_task(task_id: str) -> Task | None:
    """Возвращает задачу из БД по ID."""
    async with get_session() as session:
        task = await session.get(Task, task_id)
        if task is None:
            return None
        return task


async def list_tasks(limit: int = 20, offset: int = 0) -> tuple[list[Task], int]:
    """Возвращает задачи с пагинацией."""
    async with get_session() as session:
        tasks_result = await session.execute(
            select(Task)
            .order_by(Task.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        tasks = list(tasks_result.scalars().all())

        count_result = await session.execute(
            select(func.count()).select_from(Task)
        )
        total = count_result.scalar_one()
        return tasks, total


async def cancel_task(task_id: str) -> Task | None:
    """Отменяет задачу с блокировкой строки (пессимистичная блокировка)."""
    log.info("cancel_task_started", task_id=task_id)
    async with get_session() as session:
        task = await session.get(Task, task_id)
        if task is None:
            log.warning("cancel_task_not_found", task_id=task_id)
            return None
        if task.status == TaskStatus.COMPLETED:
            log.warning(
                "cancel_task_already_completed",
                task_id=task_id,
                status=task.status.value,
            )
            raise ValueError(f"Task {task_id} is already completed")
        task.status = TaskStatus.CANCELLED
        await session.commit()
        log.info("task_cancelled", task_id=task_id)
        return task


async def update_task_status(
    task_id: str,
    status: TaskStatus,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Обновляет статус задачи и опционально результат/ошибку в БД."""
    async with get_session() as session:
        task = await session.get(Task, task_id)
        if task is None:
            log.error("task_not_found", task_id=task_id)
            return
        task.status = status
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error
        await session.commit()
        log.info("task_status_updated", task_id=task_id, status=status.value)


async def cache_result(task_id: str, result: dict[str, Any]) -> None:
    """Кэширует результат задачи в Redis с TTL."""
    key = f"{TASK_RESULT_PREFIX}{task_id}"
    await redis_client.cache_set(key, result, ttl=TASK_CACHE_TTL)
    log.info("result_cached", task_id=task_id, ttl=TASK_CACHE_TTL)


async def get_cached_result(task_id: str) -> dict[str, Any] | None:
    """Проверяет кэш результата задачи в Redis."""
    key = f"{TASK_RESULT_PREFIX}{task_id}"
    return await redis_client.cache_get(key)


async def check_rate_limit_api() -> bool:
    """Проверяет rate-limit для API-запросов (возвращает True если разрешено)."""
    allowed, count = await redis_client.check_rate_limit(RATE_LIMIT_KEY)
    if not allowed:
        RATE_LIMIT_HITS.inc()
    return allowed


class DeadLetterMiddleware:
    """Middleware для перемещения задач в dead-letter очередь."""

    def __init__(self, broker: Any) -> None:
        self.broker = broker

    async def on_error(self, message: Any, error: Exception) -> Any:
        attempts = int(message.labels.get("attempts", 0))
        max_retries = int(message.labels.get("max_retries", 3))
        if attempts >= max_retries:
            log.warning(
                "task_moved_to_dlq",
                task_id=message.message_id,
                error=str(error)[:200],
            )
            await self.broker.kick(
                message,
                routing_key=settings.task.dead_letter_queue,
                queue_name=settings.task.dead_letter_queue,
            )
        return message
