"""Redis-клиент: кэш, rate-limit, очереди (list/stream)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import redis.asyncio as aioredis

from app.config import settings
from app.utils.logger import get_logger

log = get_logger("redis")


class RedisClient:
    """Обёртка над redis.asyncio для асинхронной работы."""

    def __init__(self, url: str | None = None) -> None:
        self._url = url or settings.redis.url
        self._pool: aioredis.Redis | None = None

    async def connect(self) -> None:
        """Создаёт подключение к Redis."""
        if self._pool is not None:
            return
        self._pool = aioredis.from_url(
            self._url,
            socket_timeout=settings.redis.socket_timeout,
            socket_connect_timeout=settings.redis.socket_connect_timeout,
            decode_responses=settings.redis.decode_responses,
        )
        await self._pool.ping()
        log.info("redis_connected", url=self._url)

    async def close(self) -> None:
        """Закрывает подключение."""
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None

    @property
    def client(self) -> aioredis.Redis:
        """Возвращает активный клиент Redis."""
        if self._pool is None:
            raise RuntimeError("Redis client not connected. Call connect() first.")
        return self._pool

    # ── Кэш ──────────────────────────────────────────────────────────────

    async def cache_get(self, key: str) -> dict[str, Any] | None:
        """Получает значение из кэша по ключу."""
        data = await self.client.get(key)
        if data is None:
            return None
        return json.loads(data)  # type: ignore[return-value]

    async def cache_set(
        self,
        key: str,
        value: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        """Сохраняет значение в кэш с TTL."""
        await self.client.set(key, json.dumps(value), ex=ttl or settings.task.default_ttl)

    async def cache_delete(self, key: str) -> None:
        """Удаляет значение из кэша."""
        await self.client.delete(key)

    # ── Rate limiting (fixed window counter) ─────────────────────────────

    async def check_rate_limit(
        self,
        key: str,
        limit: int | None = None,
        window: int | None = None,
    ) -> tuple[bool, int]:
        """Проверяет rate limit.

        Returns:
            (allowed, current_count) — разрешён ли запрос и текущий счётчик.
        """
        limit = limit or settings.task.rate_limit
        window = window or settings.task.rate_limit_window
        redis_key = f"rate_limit:{key}"
        current = await self.client.incr(redis_key)
        if current == 1:
            await self.client.expire(redis_key, window)
        return current <= limit, current

    # ── Очереди (Redis list) ──────────────────────────────────────────────

    async def queue_push(self, queue: str, task_id: str) -> None:
        """Добавляет задачу в конец очереди (list)."""
        await self.client.rpush(queue, task_id)

    async def queue_pop(self, queue: str, timeout: float = 1.0) -> str | None:
        """Извлекает задачу из начала очереди (list) с блокировкой."""
        result = await self.client.blpop(queue, timeout=int(timeout))
        if result is None:
            return None
        return result[1]  # type: ignore[index]

    async def queue_size(self, queue: str) -> int:
        """Возвращает размер очереди (list)."""
        return await self.client.llen(queue)

    # ── Очереди (Redis stream) ────────────────────────────────────────────

    async def stream_add(self, stream: str, data: dict[str, Any]) -> str:
        """Добавляет запись в поток (stream)."""
        return await self.client.xadd(stream, data)

    async def stream_read(
        self,
        stream: str,
        count: int = 1,
        block_ms: int = 1000,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Считывает записи из потока (stream)."""
        result = await self.client.xread(
            {stream: "0-0"},
            count=count,
            block=block_ms,
        )
        if not result:
            return []
        entries: list[tuple[str, dict[str, Any]]] = []
        for _, fields in result:
            for msg_id, msg_data in fields:
                entries.append((msg_id, msg_data))
        return entries

    async def stream_ack(self, stream: str, group: str, msg_id: str) -> None:
        """Подтверждает обработку записи в consumer group."""
        await self.client.xack(stream, group, msg_id)

    async def stream_group_create(
        self,
        stream: str,
        group: str,
        start_id: str = "0-0",
    ) -> None:
        """Создаёт consumer group для потока."""
        try:
            await self.client.xgroup_create(stream, group, id=start_id, mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise


# Глобальный экземпляр для convenience
redis_client = RedisClient()


__all__ = ["RedisClient", "redis_client"]