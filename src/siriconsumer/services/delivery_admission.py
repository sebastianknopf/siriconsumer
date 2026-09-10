from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from siriconsumer.interfaces.intf_delivery_admission import DeliveryAdmissionClosedError


@dataclass(slots=True)
class _AdmissionState:
    accepting: bool = True
    active_leases: int = 0
    closing_event: asyncio.Event = field(default_factory=asyncio.Event)
    drained_event: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        self.drained_event.set()


class _DeliveryLease:
    def __init__(
        self,
        admission: DeliveryAdmissionController,
        subscription_ref: str,
        state: _AdmissionState,
    ) -> None:
        self._admission = admission
        self._subscription_ref = subscription_ref
        self._state = state
        self._released = False

    @property
    def closing(self) -> bool:
        return self._state.closing_event.is_set()

    async def wait_until_closing(self) -> None:
        await self._state.closing_event.wait()

    async def release(self) -> None:
        if self._released:
            return
        self._released = True

        await self._admission._release(self._subscription_ref, self._state)


class DeliveryAdmissionController:
    """Coordinates inbound deliveries with subscription termination.

    A delivery that acquires a lease before termination begins is allowed to finish.
    Closing a subscription prevents new leases and signals existing leases that their
    normal DirectDelivery throttle timeout should no longer abort the accepted request.
    """

    def __init__(self) -> None:
        self._states: dict[str, _AdmissionState] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, subscription_ref: str) -> _DeliveryLease:
        async with self._lock:
            state = self._states.setdefault(subscription_ref, _AdmissionState())
            if not state.accepting:
                raise DeliveryAdmissionClosedError(subscription_ref)

            state.active_leases += 1
            state.drained_event.clear()

            return _DeliveryLease(self, subscription_ref, state)

    async def close(self, subscription_ref: str) -> None:
        async with self._lock:
            state = self._states.setdefault(subscription_ref, _AdmissionState())
            state.accepting = False
            state.closing_event.set()

            if state.active_leases == 0:
                state.drained_event.set()

    async def reopen(self, subscription_ref: str) -> None:
        async with self._lock:
            state = self._states.setdefault(subscription_ref, _AdmissionState())
            state.accepting = True
            state.closing_event.clear()

    async def wait_until_drained(self, subscription_ref: str) -> None:
        async with self._lock:
            state = self._states.get(subscription_ref)
            if state is None or state.active_leases == 0:
                return

            drained_event = state.drained_event

        await drained_event.wait()

    async def _release(self, subscription_ref: str, state: _AdmissionState) -> None:
        async with self._lock:
            if state.active_leases <= 0:
                return

            state.active_leases -= 1
            if state.active_leases == 0:
                state.drained_event.set()
