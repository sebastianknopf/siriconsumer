from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from siriconsumer.domain.enums import SubscriptionStatus
from siriconsumer.domain.models import SubscriptionCreate, SubscriptionRecord
from siriconsumer.interfaces.intf_siri_client import SiriClient
from siriconsumer.interfaces.intf_subscription_repository import SubscriptionRepository

logger = logging.getLogger(__name__)


class SubscriptionManager:
    def __init__(self, repository: SubscriptionRepository, siri_client: SiriClient) -> None:
        self._repository = repository
        self._siri_client = siri_client
        self._locks: dict[UUID, asyncio.Lock] = {}

    async def create(self, config: SubscriptionCreate) -> SubscriptionRecord:
        record = await self._repository.create(config)
        await self._activate(record)

        refreshed = await self._repository.get(record.id)

        assert refreshed is not None
        return refreshed

    async def terminate(self, subscription_id: UUID) -> SubscriptionRecord:
        record = await self._require(subscription_id)
        async with self._lock(subscription_id):
            await self._repository.update_status(subscription_id, SubscriptionStatus.TERMINATING)

            try:
                await self._siri_client.terminate(record)
                await self._repository.update_status(subscription_id, SubscriptionStatus.TERMINATED)
            except Exception as exc:
                await self._repository.update_status(subscription_id, SubscriptionStatus.FAILED, str(exc))
                raise

        return await self._require(subscription_id)

    async def recover(self, subscription_id: UUID) -> SubscriptionRecord:
        record = await self._require(subscription_id)
        async with self._lock(subscription_id):
            await self._recover_locked(record)

        return await self._require(subscription_id)

    async def recover_all_startup(self) -> None:
        for record in await self._repository.list_recoverable():
            try:
                await self.recover(record.id)
            except Exception:
                logger.exception("Startup recovery failed subscription_id=%s", record.id)

    async def recover_provider(self, provider_url: str) -> None:
        records = await self._repository.list_by_provider(provider_url)
        for record in records:
            if record.status is SubscriptionStatus.TERMINATED:
                continue

            try:
                await self.recover(record.id)
            except Exception:
                logger.exception(
                    "Provider recovery failed provider=%s subscription_id=%s",
                    provider_url,
                    record.id,
                )

    async def _activate(self, record: SubscriptionRecord) -> None:
        async with self._lock(record.id):
            try:
                await self._repository.update_status(record.id, SubscriptionStatus.CREATING)

                current = await self._require(record.id)

                await self._siri_client.subscribe(current)
                await self._repository.update_status(record.id, SubscriptionStatus.ACTIVE)
            except Exception as exc:
                await self._repository.update_status(record.id, SubscriptionStatus.FAILED, str(exc))
                raise

    async def _recover_locked(self, record: SubscriptionRecord) -> None:
        await self._repository.update_status(record.id, SubscriptionStatus.DEGRADED)
        try:
            try:
                await self._siri_client.terminate(record)
            except Exception:
                logger.warning(
                    "Old subscription termination failed during recovery; continuing subscription_id=%s",
                    record.id,
                    exc_info=True,
                )

            current = await self._require(record.id)

            await self._repository.update_status(record.id, SubscriptionStatus.CREATING)
            await self._siri_client.subscribe(current)
            await self._repository.update_status(record.id, SubscriptionStatus.ACTIVE)
        except Exception as exc:
            await self._repository.update_status(record.id, SubscriptionStatus.FAILED, str(exc))
            raise

    async def _require(self, subscription_id: UUID) -> SubscriptionRecord:
        record = await self._repository.get(subscription_id)
        if record is None:
            raise KeyError(str(subscription_id))

        return record

    def _lock(self, subscription_id: UUID) -> asyncio.Lock:
        return self._locks.setdefault(subscription_id, asyncio.Lock())
