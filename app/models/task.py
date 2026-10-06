"""Модель задачи (SQLAlchemy 2.0, асинхронно)."""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import DateTime


class Base(DeclarativeBase):
    """Базовый класс для моделей."""


class TaskStatus(str, enum.Enum):
    """Статус задачи."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


class Task(Base):
    """Задача, поставленная в очередь."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        comment="UUID задачи",
    )
    type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="Тип задачи (send_email, process_data, generate_report)",
    )
    status: Mapped[TaskStatus] = mapped_column(
        default=TaskStatus.PENDING,
        nullable=False,
        index=True,
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Данные для обработки",
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Результат обработки",
    )
    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Текст последней ошибки",
    )
    retries: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Количество попыток",
    )
    max_retries: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
        comment="Максимальное количество retry",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="Время создания",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="Время последнего обновления",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Время начала обработки",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Время завершения обработки",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Task(id={self.id!r}, type={self.type!r}, status={self.status!r})>"


__all__ = ["Base", "Task", "TaskStatus"]