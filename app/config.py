"""Конфигурация приложения через Pydantic Settings.

Все настройки читаются из переменных окружения (или .env).
Для тестов используются значения по умолчанию, которые можно переопределить
через фикстуры.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RedisSettings(BaseSettings):
    """Настройки Redis."""

    model_config = SettingsConfigDict(env_prefix="REDIS_")

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = None
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 5.0
    decode_responses: bool = True

    @property
    def url(self) -> str:
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class RabbitMQSettings(BaseSettings):
    """Настройки RabbitMQ."""

    model_config = SettingsConfigDict(env_prefix="RABBITMQ_")

    host: str = "localhost"
    port: int = 5672
    user: str = "guest"
    password: str = "guest"
    virtual_host: str = "/"
    heartbeat: int = 60
    connection_timeout: float = 10.0

    @property
    def url(self) -> str:
        return (
            f"amqp://{self.user}:{self.password}@"
            f"{self.host}:{self.port}{self.virtual_host}"
        )


class PostgresSettings(BaseSettings):
    """Настройки PostgreSQL."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_")

    host: str = "localhost"
    port: int = 5432
    user: str = "taskqueue"
    password: str = "taskqueue"
    db: str = "taskqueue"
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: float = 30.0
    pool_recycle: int = 3600

    @property
    def url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}@"
            f"{self.host}:{self.port}/{self.db}"
        )


class TaskSettings(BaseSettings):
    """Настройки обработки задач."""

    model_config = SettingsConfigDict(env_prefix="TASK_")

    max_retries: int = Field(default=3, description="Максимальное количество retry")
    retry_delay: float = Field(default=1.0, description="Задержка между retry (сек)")
    task_timeout: float = Field(default=60.0, description="Таймаут выполнения задачи (сек)")
    default_ttl: int = Field(default=3600, description="TTL кэша результатов (сек)")
    rate_limit: int = Field(default=100, description="Максимум запросов в минуту")
    rate_limit_window: int = Field(default=60, description="Окно rate-limit (сек)")
    dead_letter_queue: str = Field(default="tasks.dlq", description="Название DLQ")


class Settings(BaseSettings):
    """Общие настройки приложения."""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Async Task Queue"
    app_version: str = "1.0.0"
    debug: bool = False

    redis: RedisSettings = RedisSettings()
    rabbitmq: RabbitMQSettings = RabbitMQSettings()
    postgres: PostgresSettings = PostgresSettings()
    task: TaskSettings = TaskSettings()


settings = Settings()