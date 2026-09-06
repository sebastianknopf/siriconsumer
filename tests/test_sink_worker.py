from __future__ import annotations

import asyncio

import pytest

from siriconsumer.config import Settings
from siriconsumer.domain.enums import SubscriptionStatus
from siriconsumer.domain.models import SpoolMetadata, SubscriptionCreate, SubscriptionRecord
from siriconsumer.infrastructure.file_spool import FileDurableSpool
from siriconsumer.services.sink_worker import SinkWorkerPool


def _subscription() -> SubscriptionRecord:
    config = SubscriptionCreate.model_validate(
        {
            "provider_url": "https://publisher.example/siri",
            "service": "VM",
            "delivery_mode": "direct",
            "requestor_ref": "consumer",
            "subscriber_ref": "consumer",
            "subscription_ref": "sub-1",
            "sink": {"type": "directory", "path": "/tmp/output"},
        }
    )
    return SubscriptionRecord(config=config, status=SubscriptionStatus.ACTIVE)


class Repository:
    async def get(self, subscription_ref: str) -> SubscriptionRecord | None:
        return _subscription() if subscription_ref == "sub-1" else None


class FailingSink:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def write(self, subscription, metadata, payload: bytes) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("sink unavailable")

    async def close(self) -> None:
        return None


class Factory:
    def __init__(self, sink: FailingSink) -> None:
        self.sink = sink

    def get(self, subscription):
        return self.sink


@pytest.mark.asyncio
async def test_worker_allows_five_retries_then_drops_message(tmp_path) -> None:
    spool = FileDurableSpool(tmp_path / "spool", max_messages_per_subscription=100)
    await spool.initialize()
    entry = await spool.put(SpoolMetadata(subscription_ref="sub-1"), b"payload")
    sink = FailingSink(failures=99)
    settings = Settings(
        spool_worker_count=1,
        spool_max_retries=5,
        spool_retry_base_seconds=0.001,
        spool_retry_max_seconds=0.001,
    )
    pool = SinkWorkerPool(settings, spool, Repository(), Factory(sink))  # type: ignore[arg-type]

    await pool.start()
    for _ in range(100):
        if not entry.payload_path.exists():
            break
        await asyncio.sleep(0.005)
    await pool.stop()

    assert sink.calls == 6  # initial attempt + five retries
    assert not entry.payload_path.exists()
    assert not entry.metadata_path.exists()


@pytest.mark.asyncio
async def test_worker_succeeds_on_fifth_retry(tmp_path) -> None:
    spool = FileDurableSpool(tmp_path / "spool", max_messages_per_subscription=100)
    await spool.initialize()
    entry = await spool.put(SpoolMetadata(subscription_ref="sub-1"), b"payload")
    sink = FailingSink(failures=5)
    settings = Settings(
        spool_worker_count=1,
        spool_max_retries=5,
        spool_retry_base_seconds=0.001,
        spool_retry_max_seconds=0.001,
    )
    pool = SinkWorkerPool(settings, spool, Repository(), Factory(sink))  # type: ignore[arg-type]

    await pool.start()
    for _ in range(100):
        if not entry.payload_path.exists():
            break
        await asyncio.sleep(0.005)
    await pool.stop()

    assert sink.calls == 6
    assert not entry.payload_path.exists()
