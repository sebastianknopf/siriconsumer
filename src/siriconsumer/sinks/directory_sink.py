from __future__ import annotations

import asyncio
from pathlib import Path

from siriconsumer.domain.models import DirectorySinkConfig, SpoolMetadata, SubscriptionRecord


class DirectorySink:
    def __init__(self, config: DirectorySinkConfig) -> None:
        self._config = config

    async def write(self, subscription: SubscriptionRecord, metadata: SpoolMetadata, payload: bytes) -> None:
        await asyncio.to_thread(self._write_sync, subscription, metadata, payload)

    async def close(self) -> None:
        return None

    def _write_sync(self, subscription: SubscriptionRecord, metadata: SpoolMetadata, payload: bytes) -> None:
        target_dir = self._config.path / subscription.config.subscription_ref
        target_dir.mkdir(parents=True, exist_ok=True)

        name = f"{metadata.received_at.strftime('%Y%m%dT%H%M%S.%fZ')}_{metadata.message_id}.xml"
        target = target_dir / name

        temp = Path(f"{target}.tmp")
        temp.write_bytes(payload)
        temp.replace(target)
