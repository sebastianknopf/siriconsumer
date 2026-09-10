from __future__ import annotations

from typing import Literal, Protocol

CommunicationDirection = Literal["incoming", "outgoing"]
CommunicationKind = Literal["request", "response"]


class CommunicationMonitor(Protocol):
    @property
    def has_active_connection(self) -> bool:
        """Return whether a live communication observer is connected."""
        ...

    def publish(
        self,
        *,
        direction: CommunicationDirection,
        kind: CommunicationKind,
        payload: bytes,
        endpoint: str,
        status_code: int | None = None,
    ) -> None:
        """Publish one wire message to the live observer when one is connected."""
        ...
