from __future__ import annotations

from typing import Protocol

from siriconsumer.domain.models import SubscriptionRecord
from siriconsumer.interfaces.intf_message_sink import MessageSink


class SinkFactory(Protocol):
    def get(self, subscription: SubscriptionRecord) -> MessageSink: ...

    async def close(self) -> None: ...
