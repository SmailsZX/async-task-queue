"""Настройка structlog для логирования."""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging() -> None:
    """Настраивает structlog и стандартный logging."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(message)s",
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Возвращает логгер с привязанным именем."""
    return structlog.get_logger(name)