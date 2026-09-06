from __future__ import annotations

from typing import Protocol

from siriconsumer.domain.models import SpoolMetadata, SubscriptionRecord


class MessageSink(Protocol):
    async def write(
        self, subscription: SubscriptionRecord, metadata: SpoolMetadata, payload: bytes
    ) -> None: ...

    async def close(self) -> None: ...
