"""Pydantic-схемы для задач (запросы/ответы API)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.task import TaskStatus


class TaskCreate(BaseModel):
    """Запрос на создание задачи."""

    type: str = Field(..., max_length=64, description="Тип задачи")
    payload: dict[str, Any] | None = Field(
        default=None,
        description="Данные для обработки",
    )
    max_retries: int = Field(default=3, ge=0, le=10, description="Максимум retry")


class TaskResponse(BaseModel):
    id: str
    type: str
    status: TaskStatus
    payload: dict | None = None
    result: dict | None = None
    error: str | None = None
    retries: int = 0
    max_retries: int = 3
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TaskListResponse(BaseModel):
    """Ответ со списком задач."""

    total: int
    items: list[TaskResponse]


class TaskStatusResponse(BaseModel):
    """Краткий ответ со статусом задачи."""

    id: str
    status: TaskStatus
    retries: int = Field(default=0, description="Количество попыток выполнения")


__all__ = [
    "TaskCreate",
    "TaskResponse",
    "TaskListResponse",
    "TaskStatusResponse",
]