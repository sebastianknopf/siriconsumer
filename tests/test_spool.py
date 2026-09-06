from __future__ import annotations

import asyncio

import pytest

from siriconsumer.domain.models import SpoolMetadata
from siriconsumer.infrastructure.file_spool import FileDurableSpool


@pytest.mark.asyncio
async def test_spool_evicts_oldest_without_directory_rescan(tmp_path) -> None:
    spool = FileDurableSpool(tmp_path / "spool", max_messages_per_subscription=3)
    await spool.initialize()

    entries = []
    for number in range(4):
        metadata = SpoolMetadata(subscription_ref="sub-1")
        entries.append(await spool.put(metadata, f"message-{number}".encode()))

    assert spool.pending_count("sub-1") == 3
    assert not entries[0].payload_path.exists()
    assert not entries[0].metadata_path.exists()
    assert entries[-1].payload_path.exists()


@pytest.mark.asyncio
async def test_spool_rebuilds_index_on_startup(tmp_path) -> None:
    root = tmp_path / "spool"
    first = FileDurableSpool(root, max_messages_per_subscription=100)
    await first.initialize()
    await first.put(SpoolMetadata(subscription_ref="sub-1"), b"payload")

    second = FileDurableSpool(root, max_messages_per_subscription=100)
    await second.initialize()
    assert second.pending_count("sub-1") == 1


@pytest.mark.asyncio
async def test_spool_serializes_messages_per_subscription_in_fifo_order(tmp_path) -> None:
    spool = FileDurableSpool(tmp_path / "spool", max_messages_per_subscription=100)
    await spool.initialize()

    first = await spool.put(SpoolMetadata(subscription_ref="sub-1"), b"first")
    second = await spool.put(SpoolMetadata(subscription_ref="sub-1"), b"second")

    claimed_first = await asyncio.wait_for(spool.next_pending(), timeout=0.2)
    assert claimed_first.metadata.message_id == first.metadata.message_id

    blocked_second = asyncio.create_task(spool.next_pending())
    await asyncio.sleep(0.05)
    assert not blocked_second.done()

    await spool.remove(claimed_first)
    claimed_second = await asyncio.wait_for(blocked_second, timeout=0.2)
    assert claimed_second.metadata.message_id == second.metadata.message_id


@pytest.mark.asyncio
async def test_spool_allows_different_subscriptions_in_parallel(tmp_path) -> None:
    spool = FileDurableSpool(tmp_path / "spool", max_messages_per_subscription=100)
    await spool.initialize()

    await spool.put(SpoolMetadata(subscription_ref="sub-1"), b"first")
    await spool.put(SpoolMetadata(subscription_ref="sub-2"), b"second")

    first, second = await asyncio.gather(
        asyncio.wait_for(spool.next_pending(), timeout=0.2),
        asyncio.wait_for(spool.next_pending(), timeout=0.2),
    )

    assert {first.metadata.subscription_ref, second.metadata.subscription_ref} == {
        "sub-1",
        "sub-2",
    }
