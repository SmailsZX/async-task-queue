"""Prometheus-метрики для приложения."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, generate_latest

# Счётчики задач
TASKS_TOTAL = Counter(
    "app_tasks_total",
    "Всего поставленных задач",
    ["task_type", "status"],
)

TASKS_DURATION_SECONDS = Histogram(
    "app_tasks_duration_seconds",
    "Время выполнения задачи (сек)",
    labelnames=["task_type"],
)

TASKS_RETRY_TOTAL = Counter(
    "app_tasks_retry_total",
    "Количество повторных попыток задач",
    ["task_type"],
)

# Rate limiting
RATE_LIMIT_HITS = Counter(
    "app_rate_limit_hits",
    "Количество отклонённых запросов rate-limit",
)

# Очереди
TASKS_QUEUE_SIZE = Gauge(
    "app_tasks_queue_size",
    "Текущий размер очереди задач",
    ["queue"],
)

# Health
APP_UP = Gauge(
    "app_up",
    "Приложение запущено (1 = да)",
)


def metrics_response() -> bytes:
    """Возвращает метрики в формате Prometheus exposition."""
    return generate_latest()


def content_type() -> str:
    """Возвращает Content-Type для метрик."""
    return "text/plain; version=0.0.4; charset=utf-8"


__all__ = [
    "TASKS_TOTAL",
    "TASKS_DURATION_SECONDS",
    "TASKS_RETRY_TOTAL",
    "RATE_LIMIT_HITS",
    "TASKS_QUEUE_SIZE",
    "APP_UP",
    "metrics_response",
    "content_type",
]