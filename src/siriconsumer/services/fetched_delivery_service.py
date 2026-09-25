from __future__ import annotations

import asyncio
import logging

from siriconsumer.domain.enums import SubscriptionStatus
from siriconsumer.domain.exceptions import MtlsCertificateFileError
from siriconsumer.interfaces.intf_siri_client import SiriClient
from siriconsumer.interfaces.intf_subscription_repository import SubscriptionRepository
from siriconsumer.profiles.registry import ProfileRegistry
from siriconsumer.services.delivery_service import DeliveryService

logger = logging.getLogger(__name__)


class FetchedDeliveryService:
    def __init__(
        self,
        repository: SubscriptionRepository,
        siri_client: SiriClient,
        delivery_service: DeliveryService,
        max_more_data_requests: int = 100,
        profile_registry: ProfileRegistry | None = None,
    ) -> None:
        self._repository = repository
        self._siri_client = siri_client
        self._delivery_service = delivery_service
        self._max_more_data_requests = max_more_data_requests
        self._profile_registry = profile_registry or ProfileRegistry()
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
                subscription = await self._repository.get(subscription_ref)
                if subscription is None:
                    logger.error(
                        "Fetched delivery for unknown subscription_ref=%s", subscription_ref
                    )

                    continue

                more_data_requests = 0
                while True:
                    profile = self._profile_registry.get(
                        getattr(subscription.config, "profile", "default"),
                        getattr(subscription.config, "version", "default")
                    )
                    payload = await self._siri_client.fetch_delivery(subscription)
                    await self._delivery_service.accept(
                        subscription_ref,
                        payload,
                        "application/xml",
                        profile.fetched_delivery_message_name,
                    )

                    if not profile.has_more_data(payload):
                        break

                    if more_data_requests >= self._max_more_data_requests:
                        logger.warning(
                            "Fetched delivery MoreData loop stopped at configured limit "
                            "subscription_ref=%s max_more_data_requests=%s",
                            subscription_ref,
                            self._max_more_data_requests,
                        )

                        break

                    more_data_requests += 1
            except asyncio.CancelledError:
                raise
            except MtlsCertificateFileError as exc:
                await self._repository.update_status(
                    subscription_ref, SubscriptionStatus.FAILED, str(exc)
                )
                logger.error(
                    "Fetched delivery failed because mTLS files are unavailable "
                    "worker=%s subscription_ref=%s",
                    worker_id,
                    subscription_ref,
                )
            except Exception:
                logger.exception(
                    "Fetched delivery failed worker=%s subscription_ref=%s",
                    worker_id,
                    subscription_ref,
                )

    @staticmethod
    def _has_more_data(payload: bytes) -> bool:
        return ProfileRegistry().get("default", "default").has_more_data(payload)
