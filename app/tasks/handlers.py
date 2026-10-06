"""Обработчики задач (Taskiq).

Каждый handler:
- принимает dict payload
- имитирует реальную работу (asyncio.sleep)
- при payload["fail"] = True бросает Exception для тестирования retry
- возвращает dict с результатом
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

from taskiq import TaskiqMessage

from app.utils.logger import get_logger

log = get_logger("handlers")


async def send_email(payload: dict[str, Any]) -> dict[str, Any]:
    """Имитация отправки email.

    Args:
        payload: {to, subject, body, fail?}
    """
    to = payload.get("to", "unknown@example.com")
    subject = payload.get("subject", "No subject")
    delay = payload.get("delay", 0.5)

    await asyncio.sleep(delay)

    if payload.get("fail"):
        raise RuntimeError(f"Failed to send email to {to}")

    log.info("email_sent", to=to, subject=subject)
    return {
        "ok": True,
        "type": "send_email",
        "to": to,
        "subject": subject,
        "message_id": f"msg-{random.randint(100000, 999999)}",
    }


async def process_data(payload: dict[str, Any]) -> dict[str, Any]:
    """Имитация обработки данных.

    Args:
        payload: {data, fail?, delay?}
    """
    data = payload.get("data", [])
    delay = payload.get("delay", 0.5)

    await asyncio.sleep(delay)

    if payload.get("fail"):
        raise RuntimeError("Failed to process data")

    processed = [str(item).upper() for item in data]
    log.info("data_processed", count=len(processed))
    return {
        "ok": True,
        "type": "process_data",
        "processed": processed,
        "count": len(processed),
    }


async def generate_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Имитация генерации отчёта.

    Args:
        payload: {report_type, fail?, delay?}
    """
    report_type = payload.get("report_type", "csv")
    delay = payload.get("delay", 1.0)

    await asyncio.sleep(delay)

    if payload.get("fail"):
        raise RuntimeError(f"Failed to generate {report_type} report")

    log.info("report_generated", type=report_type)
    return {
        "ok": True,
        "type": "generate_report",
        "report_type": report_type,
        "report_id": f"rep-{random.randint(1000, 9999)}",
        "rows": random.randint(10, 1000),
    }


# Реестр обработчиков
HANDLERS: dict[str, Any] = {
    "send_email": send_email,
    "process_data": process_data,
    "generate_report": generate_report,
}


def get_handler(task_type: str) -> Any:
    """Возвращает handler по типу задачи."""
    handler = HANDLERS.get(task_type)
    if handler is None:
        raise KeyError(f"Unknown task type: {task_type}")
    return handler


__all__ = [
    "send_email",
    "process_data",
    "generate_report",
    "HANDLERS",
    "get_handler",
]