from __future__ import annotations

from typing import Literal, Protocol

from siriconsumer.domain.models import SubscriptionRecord

CommunicationDirection = Literal["IN", "OUT"]
CommunicationKind = Literal["Request", "Response"]


class CommunicationLogger(Protocol):
    async def write(
        self,
        subscription: SubscriptionRecord,
        *,
        direction: CommunicationDirection,
        kind: CommunicationKind,
        payload: bytes,
    ) -> None:
        """Persist one XML payload when communication logging is enabled."""
        ...
