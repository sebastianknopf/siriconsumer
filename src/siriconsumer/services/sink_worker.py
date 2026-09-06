from __future__ import annotations

import asyncio
import logging

from siriconsumer.config import Settings
from siriconsumer.interfaces.intf_sink_factory import SinkFactory
from siriconsumer.interfaces.intf_spool import DurableSpool
from siriconsumer.interfaces.intf_subscription_repository import SubscriptionRepository

logger = logging.getLogger(__name__)


class SinkWorkerPool:
    def __init__(
        self,
        settings: Settings,
        spool: DurableSpool,
        repository: SubscriptionRepository,
        sink_factory: SinkFactory,
    ) -> None:
        self._settings = settings
        self._spool = spool
        self._repository = repository
        self._sink_factory = sink_factory
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        for index in range(self._settings.spool_worker_count):
            self._tasks.append(asyncio.create_task(self._run(index), name=f"sink-worker-{index}"))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()

    async def _run(self, worker_id: int) -> None:
        attempts: dict[str, int] = {}
        while True:
            entry = await self._spool.next_pending()
            key = str(entry.metadata.message_id)

            try:
                subscription = await self._repository.get(entry.metadata.subscription_ref)
                if subscription is None:
                    logger.error("Dropping spool entry for unknown subscription message_id=%s", key)
                    await self._spool.remove(entry)
                    continue

                payload = await asyncio.to_thread(entry.payload_path.read_bytes)
                sink = self._sink_factory.get(subscription)
                await sink.write(subscription, entry.metadata, payload)
                await self._spool.remove(entry)

                attempts.pop(key, None)
            except asyncio.CancelledError:
                raise
            except Exception:
                attempt = attempts.get(key, 0) + 1
                attempts[key] = attempt

                delay = min(
                    self._settings.spool_retry_base_seconds * (2 ** min(attempt - 1, 8)),
                    self._settings.spool_retry_max_seconds,
                )

                logger.exception(
                    "Sink delivery failed worker=%s message_id=%s retry_in=%.1fs",
                    worker_id,
                    key,
                    delay,
                )

                await asyncio.sleep(delay)
                await self._spool.requeue(entry)
