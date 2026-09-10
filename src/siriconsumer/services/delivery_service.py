from __future__ import annotations

from datetime import datetime, timezone

from siriconsumer.domain.models import SpoolMetadata
from siriconsumer.interfaces.intf_spool import DurableSpool
from siriconsumer.interfaces.intf_subscription_repository import SubscriptionRepository


class DeliveryService:
    def __init__(self, repository: SubscriptionRepository, spool: DurableSpool) -> None:
        self._repository = repository
        self._spool = spool

    async def accept(
        self,
        subscription_ref: str,
        payload: bytes,
        content_type: str | None,
        message_type: str | None,
        *,
        wait_timeout_seconds: float | None = None,
    ) -> SpoolMetadata:
        subscription = await self._repository.get(subscription_ref)
        if subscription is None:
            raise KeyError(subscription_ref)

        metadata = SpoolMetadata(
            subscription_ref=subscription.config.subscription_ref,
            content_type=content_type,
            message_type=message_type,
        )

        await self._spool.put(
            metadata,
            payload,
            wait_timeout_seconds=wait_timeout_seconds,
        )

        await self._repository.update_last_message_at(
            subscription_ref, datetime.now(timezone.utc)
        )

        return metadata
