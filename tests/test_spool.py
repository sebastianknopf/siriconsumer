from __future__ import annotations

import asyncio

import pytest

from siriconsumer.domain.models import SpoolMetadata
from siriconsumer.infrastructure.file_spool import FileDurableSpool
from siriconsumer.interfaces.intf_spool import SpoolCapacityTimeoutError


@pytest.mark.asyncio
async def test_spool_waits_for_capacity_instead_of_evicting(tmp_path) -> None:
    spool = FileDurableSpool(tmp_path / "spool", max_messages_per_subscription=1)
    await spool.initialize()

    first = await spool.put(SpoolMetadata(subscription_ref="sub-1"), b"first")
    blocked = asyncio.create_task(
        spool.put(
            SpoolMetadata(subscription_ref="sub-1"),
            b"second",
            wait_timeout_seconds=1.0,
        )
    )

    await asyncio.sleep(0.05)
    assert not blocked.done()
    assert first.payload_path.exists()
    assert first.metadata_path.exists()

    claimed = await asyncio.wait_for(spool.next_pending(), timeout=0.2)
    second = await asyncio.wait_for(blocked, timeout=0.2)

    assert claimed.metadata.message_id == first.metadata.message_id
    assert first.payload_path.exists()
    assert second.payload_path.exists()


@pytest.mark.asyncio
async def test_spool_capacity_wait_times_out_without_dropping_messages(tmp_path) -> None:
    spool = FileDurableSpool(tmp_path / "spool", max_messages_per_subscription=1)
    await spool.initialize()

    first = await spool.put(SpoolMetadata(subscription_ref="sub-1"), b"first")

    with pytest.raises(SpoolCapacityTimeoutError):
        await spool.put(
            SpoolMetadata(subscription_ref="sub-1"),
            b"second",
            wait_timeout_seconds=0.05,
        )

    assert spool.pending_count("sub-1") == 1
    assert first.payload_path.exists()
    assert first.metadata_path.exists()


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
async def test_spool_keeps_startup_backlog_above_configured_limit(tmp_path) -> None:
    root = tmp_path / "spool"
    first = FileDurableSpool(root, max_messages_per_subscription=3)
    await first.initialize()

    entries = []
    for number in range(3):
        entries.append(
            await first.put(
                SpoolMetadata(subscription_ref="sub-1"),
                f"message-{number}".encode(),
            )
        )

    second = FileDurableSpool(root, max_messages_per_subscription=1)
    await second.initialize()

    assert second.pending_count("sub-1") == 3
    assert all(entry.payload_path.exists() for entry in entries)


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


@pytest.mark.asyncio
async def test_spool_purge_removes_all_messages_for_subscription(tmp_path) -> None:
    spool = FileDurableSpool(tmp_path / "spool", max_messages_per_subscription=100)
    await spool.initialize()

    first = await spool.put(SpoolMetadata(subscription_ref="sub-1"), b"first")
    second = await spool.put(SpoolMetadata(subscription_ref="sub-1"), b"second")
    other = await spool.put(SpoolMetadata(subscription_ref="sub-2"), b"other")

    claimed = await asyncio.wait_for(spool.next_pending(), timeout=0.2)
    if claimed.metadata.subscription_ref == "sub-2":
        await spool.requeue(claimed)
        claimed = await asyncio.wait_for(spool.next_pending(), timeout=0.2)

    assert claimed.metadata.subscription_ref == "sub-1"

    purged = await spool.purge("sub-1")

    assert purged == 1
    assert spool.pending_count("sub-1") == 1
    assert claimed.payload_path.exists()
    assert claimed.metadata_path.exists()
    pending = second if claimed.metadata.message_id == first.metadata.message_id else first
    assert not pending.payload_path.exists()
    assert not pending.metadata_path.exists()
    assert other.payload_path.exists()

    await spool.remove(claimed)
    next_entry = await asyncio.wait_for(spool.next_pending(), timeout=0.2)
    assert next_entry.metadata.subscription_ref == "sub-2"


@pytest.mark.asyncio
async def test_spool_limit_counts_pending_but_not_inflight_message(tmp_path) -> None:
    spool = FileDurableSpool(tmp_path / "spool", max_messages_per_subscription=1)
    await spool.initialize()

    inflight = await spool.put(SpoolMetadata(subscription_ref="sub-1"), b"inflight")
    claimed = await asyncio.wait_for(spool.next_pending(), timeout=0.2)
    assert claimed.metadata.message_id == inflight.metadata.message_id

    pending = await spool.put(SpoolMetadata(subscription_ref="sub-1"), b"pending")
    blocked = asyncio.create_task(
        spool.put(
            SpoolMetadata(subscription_ref="sub-1"),
            b"next",
            wait_timeout_seconds=1.0,
        )
    )

    await asyncio.sleep(0.05)
    assert not blocked.done()
    assert inflight.payload_path.exists()
    assert pending.payload_path.exists()

    await spool.remove(claimed)
    next_entry = await asyncio.wait_for(spool.next_pending(), timeout=0.2)
    assert next_entry.metadata.message_id == pending.metadata.message_id

    newest = await asyncio.wait_for(blocked, timeout=0.2)
    assert newest.payload_path.exists()


@pytest.mark.asyncio
async def test_purge_preserves_inflight_and_waits_until_it_finishes(tmp_path) -> None:
    spool = FileDurableSpool(tmp_path / "spool", max_messages_per_subscription=100)
    await spool.initialize()

    inflight = await spool.put(SpoolMetadata(subscription_ref="sub-1"), b"inflight")
    pending = await spool.put(SpoolMetadata(subscription_ref="sub-1"), b"pending")
    claimed = await asyncio.wait_for(spool.next_pending(), timeout=0.2)

    purged = await spool.purge("sub-1")
    assert purged == 1
    assert inflight.payload_path.exists()
    assert not pending.payload_path.exists()

    waiter = asyncio.create_task(spool.wait_until_idle("sub-1"))
    await asyncio.sleep(0.05)
    assert not waiter.done()

    await spool.remove(claimed)
    await asyncio.wait_for(waiter, timeout=0.2)
