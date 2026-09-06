from __future__ import annotations

import asyncio
import logging

from siriconsumer.interfaces.intf_siri_client import SiriClient
from siriconsumer.interfaces.intf_subscription_repository import SubscriptionRepository
from siriconsumer.services.delivery_service import DeliveryService

logger = logging.getLogger(__name__)


class FetchedDeliveryService:
    def __init__(
        self,
        repository: SubscriptionRepository,
        siri_client: SiriClient,
        delivery_service: DeliveryService,
    ) -> None:
        self._repository = repository
        self._siri_client = siri_client
        self._delivery_service = delivery_service
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self, workers: int = 2) -> None:
        for index in range(workers):
            self._tasks.append(asyncio.create_task(self._run(index), name=f"fetch-worker-{index}"))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()

    async def schedule(self, subscription_ref: str) -> None:
        await self._queue.put(subscription_ref)

    async def _run(self, worker_id: int) -> None:
        while True:
            subscription_ref = await self._queue.get()
            try:
                subscription = await self._repository.get_by_ref(subscription_ref)
                if subscription is None:
                    logger.error("Fetched delivery for unknown subscription_ref=%s", subscription_ref)
                    continue

                payload = await self._siri_client.fetch_delivery(subscription)
                await self._delivery_service.accept(
                    subscription.id, payload, "application/xml", "DataSupplyResponse"
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Fetched delivery failed worker=%s subscription_ref=%s",
                    worker_id,
                    subscription_ref,
                )
