from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from siriconsumer.domain.models import SpoolMetadata
from siriconsumer.interfaces.intf_delivery_admission import DeliveryAdmission, DeliveryLease
from siriconsumer.interfaces.intf_spool import DurableSpool, SpoolCapacityTimeoutError
from siriconsumer.interfaces.intf_subscription_repository import SubscriptionRepository


class DeliveryService:
    def __init__(
        self,
        repository: SubscriptionRepository,
        spool: DurableSpool,
        admission: DeliveryAdmission,
    ) -> None:
        self._repository = repository
        self._spool = spool
        self._admission = admission

    async def accept(
        self,
        subscription_ref: str,
        payload: bytes,
        content_type: str | None,
        message_type: str | None,
        *,
        wait_timeout_seconds: float | None = None,
    ) -> SpoolMetadata:
        lease = await self._admission.acquire(subscription_ref)
        try:
            subscription = await self._repository.get(subscription_ref)
            if subscription is None:
                raise KeyError(subscription_ref)

            metadata = SpoolMetadata(
                subscription_ref=subscription.config.subscription_ref,
                content_type=content_type,
                message_type=message_type,
            )

            await self._put_with_termination_aware_timeout(
                lease,
                metadata,
                payload,
                wait_timeout_seconds,
            )

            await self._repository.update_last_message_at(
                subscription_ref, datetime.now(timezone.utc)
            )
            return metadata
        finally:
            await lease.release()

    async def _put_with_termination_aware_timeout(
        self,
        lease: DeliveryLease,
        metadata: SpoolMetadata,
        payload: bytes,
        wait_timeout_seconds: float | None,
    ) -> None:
        if wait_timeout_seconds is None or lease.closing:
            await self._spool.put(metadata, payload)
            return

        put_task = asyncio.create_task(self._spool.put(metadata, payload))
        closing_task = asyncio.create_task(lease.wait_until_closing())
        timeout_task = asyncio.create_task(asyncio.sleep(wait_timeout_seconds))
        tasks = {put_task, closing_task, timeout_task}

        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            if put_task in done:
                await put_task
                return

            if closing_task in done:
                await put_task
                return

            # Normal DirectDelivery throttling timed out before termination began.
            put_task.cancel()
            await asyncio.gather(put_task, return_exceptions=True)

            raise SpoolCapacityTimeoutError(
                f"Spool capacity timeout for subscription_ref={metadata.subscription_ref}"
            )
        finally:
            for task in (closing_task, timeout_task):
                task.cancel()

            await asyncio.gather(closing_task, timeout_task, return_exceptions=True)
