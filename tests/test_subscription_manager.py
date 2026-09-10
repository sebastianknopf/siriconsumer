from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from siriconsumer.domain.enums import SubscriptionStatus
from siriconsumer.domain.models import SubscriptionCreate, SubscriptionRecord
from siriconsumer.interfaces.intf_delivery_admission import DeliveryAdmissionClosedError
from siriconsumer.services.delivery_admission import DeliveryAdmissionController
from siriconsumer.services.subscription_manager import SubscriptionManager


def _config(subscription_ref: str = "sub-1") -> SubscriptionCreate:
    return SubscriptionCreate.model_validate(
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


@dataclass
class FakeRepository:
    record: SubscriptionRecord | None

    async def get(self, subscription_ref: str) -> SubscriptionRecord | None:
        if self.record is None or self.record.config.subscription_ref != subscription_ref:
            return None
        return self.record

    async def update_status(
        self, subscription_ref: str, status: SubscriptionStatus, error: str | None = None
    ) -> None:
        record = await self.get(subscription_ref)
        if record is not None:
            record.status = status
            record.last_error = error

    async def delete(self, subscription_ref: str) -> None:
        if await self.get(subscription_ref) is None:
            raise KeyError(subscription_ref)
        self.record = None


class FakeSiriClient:
    def __init__(self, *, fail_terminate: bool = False) -> None:
        self.fail_terminate = fail_terminate
        self.terminated_refs: list[str] = []

    async def terminate(self, subscription: SubscriptionRecord) -> None:
        self.terminated_refs.append(subscription.config.subscription_ref)
        if self.fail_terminate:
            raise RuntimeError("producer termination failed")


class FakeSpool:
    def __init__(self) -> None:
        self.empty_wait_refs: list[str] = []

    async def wait_until_empty(self, subscription_ref: str) -> None:
        self.empty_wait_refs.append(subscription_ref)


class FakeSinkFactory:
    def __init__(self) -> None:
        self.removed_refs: list[str] = []

    async def remove(self, subscription_ref: str) -> None:
        self.removed_refs.append(subscription_ref)


@pytest.mark.asyncio
async def test_successful_termination_deletes_subscription_and_cleans_runtime_state() -> None:
    repository = FakeRepository(SubscriptionRecord(config=_config(), status=SubscriptionStatus.ACTIVE))
    siri_client = FakeSiriClient()
    spool = FakeSpool()
    sink_factory = FakeSinkFactory()
    admission = DeliveryAdmissionController()
    manager = SubscriptionManager(
        repository, siri_client, spool, sink_factory, admission
    )  # type: ignore[arg-type]

    await manager.terminate("sub-1")

    assert repository.record is None
    assert siri_client.terminated_refs == ["sub-1"]
    assert spool.empty_wait_refs == ["sub-1"]
    assert sink_factory.removed_refs == ["sub-1"]


@pytest.mark.asyncio
async def test_failed_publisher_termination_keeps_subscription_as_failed() -> None:
    repository = FakeRepository(SubscriptionRecord(config=_config(), status=SubscriptionStatus.ACTIVE))
    siri_client = FakeSiriClient(fail_terminate=True)
    spool = FakeSpool()
    sink_factory = FakeSinkFactory()
    admission = DeliveryAdmissionController()
    manager = SubscriptionManager(
        repository, siri_client, spool, sink_factory, admission
    )  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="producer termination failed"):
        await manager.terminate("sub-1")

    assert repository.record is not None
    assert repository.record.status is SubscriptionStatus.FAILED
    assert spool.empty_wait_refs == []
    assert sink_factory.removed_refs == []


@pytest.mark.asyncio
async def test_termination_waits_for_preexisting_delivery_lease_before_delete() -> None:
    repository = FakeRepository(
        SubscriptionRecord(config=_config(), status=SubscriptionStatus.ACTIVE)
    )
    siri_client = FakeSiriClient()
    spool = FakeSpool()
    sink_factory = FakeSinkFactory()
    admission = DeliveryAdmissionController()
    manager = SubscriptionManager(
        repository, siri_client, spool, sink_factory, admission
    )  # type: ignore[arg-type]

    lease = await admission.acquire("sub-1")
    termination = asyncio.create_task(manager.terminate("sub-1"))

    await asyncio.sleep(0.02)
    assert repository.record is not None
    with pytest.raises(DeliveryAdmissionClosedError):
        await admission.acquire("sub-1")

    await lease.release()
    await asyncio.wait_for(termination, timeout=0.2)
    assert repository.record is None
