from __future__ import annotations

import asyncio

import pytest

from siriconsumer.domain.enums import SubscriptionStatus
from siriconsumer.domain.models import SubscriptionCreate, SubscriptionRecord
from siriconsumer.interfaces.intf_delivery_admission import DeliveryAdmissionClosedError
from siriconsumer.interfaces.intf_spool import SpoolCapacityTimeoutError
from siriconsumer.services.delivery_admission import DeliveryAdmissionController
from siriconsumer.services.delivery_service import DeliveryService


def _record(subscription_ref: str = "sub-1") -> SubscriptionRecord:
    config = SubscriptionCreate.model_validate(
        {
            "provider_url": "https://publisher.example/siri",
            "service": "VM",
            "delivery_mode": "direct",
            "requestor_ref": "consumer",
            "subscriber_ref": "consumer",
            "subscription_ref": subscription_ref,
            "sink": {"type": "directory", "path": "/tmp/output"},
        }
    )
    return SubscriptionRecord(config=config, status=SubscriptionStatus.ACTIVE)


class Repository:
    def __init__(self) -> None:
        self.record = _record()
        self.updated = 0

    async def get(self, subscription_ref: str):
        return self.record if subscription_ref == "sub-1" else None

    async def update_last_message_at(self, subscription_ref, last_message_at) -> None:
        self.updated += 1


class BlockingSpool:
    def __init__(self) -> None:
        self.capacity = asyncio.Event()
        self.puts = 0

    async def put(self, metadata, payload, *, wait_timeout_seconds=None):
        await self.capacity.wait()
        self.puts += 1


@pytest.mark.asyncio
async def test_new_delivery_is_rejected_after_admission_closes() -> None:
    admission = DeliveryAdmissionController()
    await admission.close("sub-1")

    with pytest.raises(DeliveryAdmissionClosedError):
        await admission.acquire("sub-1")


@pytest.mark.asyncio
async def test_delivery_throttle_timeout_is_disabled_when_termination_starts() -> None:
    repository = Repository()
    spool = BlockingSpool()
    admission = DeliveryAdmissionController()
    service = DeliveryService(repository, spool, admission)  # type: ignore[arg-type]

    delivery = asyncio.create_task(
        service.accept(
            "sub-1",
            b"payload",
            "application/xml",
            "ServiceDelivery",
            wait_timeout_seconds=0.05,
        )
    )
    await asyncio.sleep(0.01)
    await admission.close("sub-1")

    await asyncio.sleep(0.08)
    assert not delivery.done()

    spool.capacity.set()
    await asyncio.wait_for(delivery, timeout=0.2)
    await admission.wait_until_drained("sub-1")

    assert spool.puts == 1
    assert repository.updated == 1


@pytest.mark.asyncio
async def test_normal_delivery_still_times_out_when_not_terminating() -> None:
    repository = Repository()
    spool = BlockingSpool()
    admission = DeliveryAdmissionController()
    service = DeliveryService(repository, spool, admission)  # type: ignore[arg-type]

    with pytest.raises(SpoolCapacityTimeoutError):
        await service.accept(
            "sub-1",
            b"payload",
            "application/xml",
            "ServiceDelivery",
            wait_timeout_seconds=0.02,
        )
