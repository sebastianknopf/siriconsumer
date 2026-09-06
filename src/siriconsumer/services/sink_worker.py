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

                while True:
                    try:
                        await sink.write(subscription, entry.metadata, payload)
                        await self._spool.remove(entry)
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        if entry.metadata.retry_count >= self._settings.spool_max_retries:
                            logger.warning(
                                "Sink delivery permanently failed; dropping message after %s retries "
                                "worker=%s subscription_ref=%s message_id=%s",
                                entry.metadata.retry_count,
                                worker_id,
                                entry.metadata.subscription_ref,
                                key,
                                exc_info=True,
                            )
                            await self._spool.remove(entry)

                            break

                        retry_count = await self._spool.record_retry(entry)
                        delay = min(
                            self._settings.spool_retry_base_seconds
                            * (2 ** min(retry_count - 1, 8)),
                            self._settings.spool_retry_max_seconds,
                        )

                        logger.warning(
                            "Sink delivery failed; retry %s/%s in %.1fs worker=%s "
                            "subscription_ref=%s message_id=%s",
                            retry_count,
                            self._settings.spool_max_retries,
                            delay,
                            worker_id,
                            entry.metadata.subscription_ref,
                            key,
                            exc_info=True,
                        )

                        await asyncio.sleep(delay)
            except asyncio.CancelledError:
                await self._spool.requeue(entry)
                raise
            except Exception:
                logger.exception(
                    "Unexpected sink worker failure; dropping message worker=%s "
                    "subscription_ref=%s message_id=%s",
                    worker_id,
                    entry.metadata.subscription_ref,
                    key,
                )
                await self._spool.remove(entry)
