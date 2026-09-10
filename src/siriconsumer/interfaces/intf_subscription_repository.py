from __future__ import annotations

from datetime import datetime
from typing import Protocol

from siriconsumer.domain.enums import SubscriptionStatus
from siriconsumer.domain.models import SubscriptionCreate, SubscriptionRecord


class SubscriptionAlreadyExistsError(ValueError):
    """Raised when a subscription_ref already exists in durable storage."""


class SubscriptionRepository(Protocol):
    async def initialize(self) -> None: ...

    async def create(self, config: SubscriptionCreate) -> SubscriptionRecord: ...

    async def get(self, subscription_ref: str) -> SubscriptionRecord | None: ...

    async def list_all(self) -> list[SubscriptionRecord]: ...

    async def list_recoverable(self) -> list[SubscriptionRecord]: ...

    async def list_by_provider(self, provider_url: str) -> list[SubscriptionRecord]: ...

    async def delete(self, subscription_ref: str) -> None: ...

    async def update_status(
        self, subscription_ref: str, status: SubscriptionStatus, error: str | None = None
    ) -> None: ...

    async def update_last_message_at(
        self, subscription_ref: str, last_message_at: datetime
    ) -> None: ...

    async def update_heartbeat(
        self,
        subscription_ref: str,
        last_heartbeat_at: datetime,
        service_started_time: datetime | None,
    ) -> None: ...

    async def update_service_started_time(
        self, subscription_ref: str, service_started_time: datetime
    ) -> None: ...
