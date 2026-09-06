from __future__ import annotations

from uuid import uuid4

import pytest

from siriconsumer.domain.models import SpoolMetadata
from siriconsumer.infrastructure.file_spool import FileDurableSpool


@pytest.mark.asyncio
async def test_spool_evicts_oldest_without_directory_rescan(tmp_path) -> None:
    subscription_id = uuid4()
    spool = FileDurableSpool(tmp_path / "spool", max_messages_per_subscription=3)
    await spool.initialize()

    entries = []
    for number in range(4):
        metadata = SpoolMetadata(
            subscription_id=subscription_id,
            subscription_ref="sub-1",
        )
        entries.append(await spool.put(metadata, f"message-{number}".encode()))

    assert spool.pending_count(subscription_id) == 3
    assert not entries[0].payload_path.exists()
    assert not entries[0].metadata_path.exists()
    assert entries[-1].payload_path.exists()


@pytest.mark.asyncio
async def test_spool_rebuilds_index_on_startup(tmp_path) -> None:
    subscription_id = uuid4()
    root = tmp_path / "spool"
    first = FileDurableSpool(root, max_messages_per_subscription=100)
    await first.initialize()
    await first.put(
        SpoolMetadata(subscription_id=subscription_id, subscription_ref="sub-1"),
        b"payload",
    )

    second = FileDurableSpool(root, max_messages_per_subscription=100)
    await second.initialize()
    assert second.pending_count(subscription_id) == 1
