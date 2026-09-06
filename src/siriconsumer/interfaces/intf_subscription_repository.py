from __future__ import annotations

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

    async def save(self, record: SubscriptionRecord) -> None: ...

    async def update_status(
        self, subscription_ref: str, status: SubscriptionStatus, error: str | None = None
    ) -> None: ...
