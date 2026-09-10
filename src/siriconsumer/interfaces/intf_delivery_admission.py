from __future__ import annotations

from typing import Protocol


class DeliveryAdmissionClosedError(RuntimeError):
    """Raised when a subscription no longer accepts new inbound deliveries."""


class DeliveryLease(Protocol):
    @property
    def closing(self) -> bool: ...

    async def wait_until_closing(self) -> None: ...

    async def release(self) -> None: ...


class DeliveryAdmission(Protocol):
    async def acquire(self, subscription_ref: str) -> DeliveryLease: ...

    async def close(self, subscription_ref: str) -> None: ...

    async def reopen(self, subscription_ref: str) -> None: ...

    async def wait_until_drained(self, subscription_ref: str) -> None: ...
