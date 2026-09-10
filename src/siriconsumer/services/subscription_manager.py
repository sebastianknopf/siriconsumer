from __future__ import annotations

import asyncio
import logging

from siriconsumer.domain.enums import SubscriptionStatus
from siriconsumer.domain.models import SubscriptionCreate, SubscriptionRecord
from siriconsumer.interfaces.intf_delivery_admission import DeliveryAdmission
from siriconsumer.interfaces.intf_sink_factory import SinkFactory
from siriconsumer.interfaces.intf_siri_client import SiriClient
from siriconsumer.interfaces.intf_spool import DurableSpool
from siriconsumer.interfaces.intf_subscription_repository import SubscriptionRepository

logger = logging.getLogger(__name__)


class SubscriptionManager:
    def __init__(
        self,
        repository: SubscriptionRepository,
        siri_client: SiriClient,
        spool: DurableSpool,
        sink_factory: SinkFactory,
        delivery_admission: DeliveryAdmission,
    ) -> None:
        self._repository = repository
        self._siri_client = siri_client
        self._spool = spool
        self._sink_factory = sink_factory
        self._delivery_admission = delivery_admission
        self._locks: dict[str, asyncio.Lock] = {}

    async def create(self, config: SubscriptionCreate) -> SubscriptionRecord:
        record = await self._repository.create(config)
        await self._delivery_admission.reopen(config.subscription_ref)
        await self._activate(record)
        return await self._require(config.subscription_ref)

    async def terminate(self, subscription_ref: str) -> None:
        record = await self._require(subscription_ref)
        async with self._lock(subscription_ref):
            # Establish the local cut-off before telling the publisher to terminate.
            # Requests that already own a delivery lease may still finish; requests
            # arriving after this point are rejected before they can enter the spool.
            await self._delivery_admission.close(subscription_ref)
            await self._repository.update_status(
                subscription_ref, SubscriptionStatus.TERMINATING
            )

            try:
                await self._siri_client.terminate(record)
            except Exception as exc:
                await self._repository.update_status(
                    subscription_ref, SubscriptionStatus.FAILED, str(exc)
                )

                await self._delivery_admission.reopen(subscription_ref)
                raise

            # Any DirectDelivery request admitted before the cut-off is allowed to
            # finish. If it was throttled when termination started, its normal HTTP
            # throttle timeout is disabled so it can persist as the sink drains.
            await self._delivery_admission.wait_until_drained(subscription_ref)

            # No new inbound DirectDelivery can enter the spool now. Drain every
            # message already accepted for this subscription through the configured
            # sink, including bounded retries, before deleting durable state.
            await self._spool.wait_until_empty(subscription_ref)

            await self._repository.delete(subscription_ref)
            # The temporary 410 termination window ends exactly when durable
            # subscription state is removed. Later callbacks are unknown and must
            # therefore be reported as HTTP 404 until the same ref is recreated.
            await self._delivery_admission.mark_deleted(subscription_ref)

            try:
                await self._sink_factory.remove(subscription_ref)
            except Exception:
                logger.warning(
                    "Failed to close sink after subscription deletion subscription_ref=%s",
                    subscription_ref,
                    exc_info=True,
                )

            logger.info(
                "Subscription terminated, drained, and deleted subscription_ref=%s",
                subscription_ref,
            )

    async def recover(self, subscription_ref: str) -> SubscriptionRecord:
        record = await self._require(subscription_ref)
        async with self._lock(subscription_ref):
            await self._recover_locked(record)

        return await self._require(subscription_ref)

    async def recover_all_startup(self) -> None:
        for record in await self._repository.list_recoverable():
            subscription_ref = record.config.subscription_ref
            try:
                await self.recover(subscription_ref)
            except Exception:
                logger.exception("Startup recovery failed subscription_ref=%s", subscription_ref)

    async def recover_provider(self, provider_url: str) -> None:
        records = await self._repository.list_by_provider(provider_url)
        for record in records:
            subscription_ref = record.config.subscription_ref
            try:
                await self.recover(subscription_ref)
            except Exception:
                logger.exception(
                    "Provider recovery failed provider=%s subscription_ref=%s",
                    provider_url,
                    subscription_ref,
                )

    async def _activate(self, record: SubscriptionRecord) -> None:
        subscription_ref = record.config.subscription_ref
        async with self._lock(subscription_ref):
            try:
                await self._repository.update_status(subscription_ref, SubscriptionStatus.CREATING)
                current = await self._require(subscription_ref)
                await self._siri_client.subscribe(current)
                await self._repository.update_status(subscription_ref, SubscriptionStatus.ACTIVE)
            except Exception as exc:
                await self._repository.update_status(subscription_ref, SubscriptionStatus.FAILED, str(exc))
                raise

    async def _recover_locked(self, record: SubscriptionRecord) -> None:
        subscription_ref = record.config.subscription_ref
        await self._repository.update_status(subscription_ref, SubscriptionStatus.DEGRADED)
        try:
            try:
                await self._siri_client.terminate(record)
            except Exception:
                logger.warning(
                    "Old subscription termination failed during recovery; continuing subscription_ref=%s",
                    subscription_ref,
                    exc_info=True,
                )

            current = await self._require(subscription_ref)
            await self._repository.update_status(subscription_ref, SubscriptionStatus.CREATING)
            await self._siri_client.subscribe(current)
            await self._repository.update_status(subscription_ref, SubscriptionStatus.ACTIVE)
        except Exception as exc:
            await self._repository.update_status(subscription_ref, SubscriptionStatus.FAILED, str(exc))
            raise

    async def _require(self, subscription_ref: str) -> SubscriptionRecord:
        record = await self._repository.get(subscription_ref)
        if record is None:
            raise KeyError(subscription_ref)
        return record

    def _lock(self, subscription_ref: str) -> asyncio.Lock:
        return self._locks.setdefault(subscription_ref, asyncio.Lock())
