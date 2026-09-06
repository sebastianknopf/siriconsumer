from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from siriconsumer.domain.models import SubscriptionRecord


@dataclass(slots=True)
class ProviderStatus:
    healthy: bool
    service_started_time: datetime | None = None


class SiriClient(Protocol):
    async def subscribe(self, subscription: SubscriptionRecord) -> None: ...

    async def terminate(self, subscription: SubscriptionRecord) -> None: ...

    async def check_status(self, provider_url: str, requestor_ref: str) -> ProviderStatus: ...

    async def fetch_delivery(self, subscription: SubscriptionRecord) -> bytes: ...
