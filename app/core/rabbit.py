"""RabbitMQ-клиент на aio-pika.

Предоставляет:
- подключение/отключение
- публикацию сообщений (publisher)
- потребление с подтверждениями (ack/nack)
- dead-letter exchange
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import aio_pika
from aio_pika.robust_connection import RobustConnection

from app.config import settings
from app.utils.logger import get_logger

log = get_logger("rabbit")


class RabbitClient:
    """Обёртка над aio-pika для асинхронной работы с RabbitMQ."""

    def __init__(self, url: str | None = None) -> None:
        self._url = url or settings.rabbitmq.url
        self._connection: RobustConnection | None = None
        self._channel: aio_pika.Channel | None = None

    async def connect(self) -> None:
        """Устанавливает устойчивое соединение с RabbitMQ."""
        if self._connection is not None and not self._connection.is_closed:
            return
        self._connection = await aio_pika.connect_robust(
            self._url,
            heartbeat=settings.rabbitmq.heartbeat,
            connection_timeout=int(settings.rabbitmq.connection_timeout * 1000),
        )
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=1)
        log.info("rabbit_connected", url=self._url)

    async def close(self) -> None:
        """Закрывает соединение."""
        if self._channel is not None and not self._channel.is_closed:
            await self._channel.close()
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._channel = None
        self._connection = None

    @property
    def channel(self) -> aio_pika.Channel:
        """Возвращает активный канал."""
        if self._channel is None or self._channel.is_closed:
            raise RuntimeError("RabbitMQ channel not open. Call connect() first.")
        return self._channel

    # ── Очереди / exchange ────────────────────────────────────────────────

    async def declare_queue(
        self,
        name: str,
        durable: bool = True,
        arguments: dict[str, Any] | None = None,
    ) -> aio_pika.Queue:
        """Объявляет очередь."""
        return await self.channel.declare_queue(
            name,
            durable=durable,
            arguments=arguments or {},
        )

    async def declare_exchange(
        self,
        name: str,
        exchange_type: aio_pika.ExchangeType = aio_pika.ExchangeType.DIRECT,
        durable: bool = True,
    ) -> aio_pika.Exchange:
        """Объявляет exchange."""
        return await self.channel.declare_exchange(
            name,
            exchange_type,
            durable=durable,
        )

    async def bind_queue(
        self,
        queue: aio_pika.Queue,
        exchange: aio_pika.Exchange,
        routing_key: str = "",
    ) -> None:
        """Привязывает очередь к exchange."""
        await queue.bind(exchange, routing_key=routing_key)

    # ── Publisher ─────────────────────────────────────────────────────────

    async def publish(
        self,
        routing_key: str,
        body: bytes,
        exchange_name: str | None = None,
        persistent: bool = True,
    ) -> None:
        """Публикует сообщение в exchange (по умолчанию "tasks")."""
        exchange_name = exchange_name or "tasks"
        exchange = await self.channel.declare_exchange(
            exchange_name,
            aio_pika.ExchangeType.DIRECT,
            durable=True,
        )
        queue = await self.channel.declare_queue(
            f"{exchange_name}_queue",
            durable=True,
        )
        await queue.bind(exchange, routing_key=routing_key)
        await exchange.publish(
            aio_pika.Message(
                body=body,
                delivery_mode=(
                    aio_pika.DeliveryMode.PERSISTENT
                    if persistent
                    else aio_pika.DeliveryMode.NOT_PERSISTENT
                ),
            ),
            routing_key=routing_key,
        )

    # ── Consumer ──────────────────────────────────────────────────────────

    async def consume(
        self,
        queue_name: str,
        callback: Callable[[aio_pika.InboundMessage], Awaitable[None]],
        no_ack: bool = False,
    ) -> None:
        """Потребляет сообщения из очереди.

        Callback вызывается для каждого сообщения. Если no_ack=False,
        callback должен вызвать message.ack() или message.nack().
        """
        queue = await self.declare_queue(queue_name)
        await queue.consume(callback)

    async def stop_consume(self, queue_name: str) -> None:
        """Останавливает потребление из очереди."""
        queue = await self.channel.get_queue(queue_name)
        await queue.stop_consuming()


# Глобальный экземпляр для convenience
rabbit_client = RabbitClient()


__all__ = ["RabbitClient", "rabbit_client"]