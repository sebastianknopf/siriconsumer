from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from siriconsumer.domain.models import SpoolMetadata
from siriconsumer.interfaces.intf_spool import DurableSpool
from siriconsumer.interfaces.intf_subscription_repository import SubscriptionRepository


class DeliveryService:
    def __init__(self, repository: SubscriptionRepository, spool: DurableSpool) -> None:
        self._repository = repository
        self._spool = spool

    async def accept(
        self,
        subscription_id: UUID,
        payload: bytes,
        content_type: str | None,
        message_type: str | None,
    ) -> SpoolMetadata:
        subscription = await self._repository.get(subscription_id)
        if subscription is None:
            raise KeyError(str(subscription_id))

        metadata = SpoolMetadata(
            subscription_id=subscription.id,
            subscription_ref=subscription.config.subscription_ref,
            content_type=content_type,
            message_type=message_type,
        )

        await self._spool.put(metadata, payload)

        subscription.last_message_at = datetime.now(timezone.utc)
        await self._repository.save(subscription)

        return metadata
