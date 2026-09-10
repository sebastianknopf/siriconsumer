from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from lxml import etree

from siriconsumer.interfaces.intf_communication_monitor import (
    CommunicationDirection,
    CommunicationKind,
)


class LiveCommunicationMonitor:
    """Expose live SIRI wire messages to at most one WebSocket observer."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._state_lock = asyncio.Lock()

    @property
    def has_active_connection(self) -> bool:
        return self._queue is not None

    def publish(
        self,
        *,
        direction: CommunicationDirection,
        kind: CommunicationKind,
        payload: bytes,
        endpoint: str,
        status_code: int | None = None,
    ) -> None:
        # This check deliberately happens before any XML parsing/decoding. When no
        # observer is connected, communication monitoring has no XML-processing cost.
        queue = self._queue
        if queue is None:
            return

        event: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "direction": direction,
            "kind": kind,
            "endpoint": endpoint,
            "xml": self._pretty_xml(payload),
        }

        if status_code is not None:
            event["status_code"] = status_code

        # The queue is intentionally live-only and process-local. It is unbounded so
        # monitoring never applies backpressure to SIRI processing. Disconnecting the
        # observer discards the queue and all not-yet-sent monitoring events.
        queue.put_nowait(event)

    async def serve(self, websocket: WebSocket) -> None:
        queue = await self._claim_connection(websocket)
        if queue is None:
            return

        sender: asyncio.Task[None] | None = None
        receiver: asyncio.Task[None] | None = None
        try:
            sender = asyncio.create_task(self._send_loop(websocket, queue))
            receiver = asyncio.create_task(self._receive_loop(websocket))
            done, pending = await asyncio.wait(
                {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
            )

            for task in pending:
                task.cancel()

            await asyncio.gather(*pending, return_exceptions=True)
            await asyncio.gather(*done, return_exceptions=True)
        except WebSocketDisconnect:
            pass
        finally:
            if sender is not None:
                sender.cancel()

            if receiver is not None:
                receiver.cancel()

            await self._release_connection(queue)

    async def _claim_connection(
        self, websocket: WebSocket
    ) -> asyncio.Queue[dict[str, Any]] | None:
        async with self._state_lock:
            if self._queue is not None:
                await websocket.accept()

                await websocket.close(
                    code=1008,
                    reason="Only one communication monitor connection is allowed",
                )

                return None

            await websocket.accept()
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            self._queue = queue

            return queue

    async def _release_connection(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._state_lock:
            if self._queue is queue:
                self._queue = None

    @staticmethod
    async def _send_loop(
        websocket: WebSocket, queue: asyncio.Queue[dict[str, Any]]
    ) -> None:
        while True:
            await websocket.send_json(await queue.get())

    @staticmethod
    async def _receive_loop(websocket: WebSocket) -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return

    @staticmethod
    def _pretty_xml(payload: bytes) -> str:
        try:
            parser = etree.XMLParser(
                remove_blank_text=True,
                resolve_entities=False,
                no_network=True,
            )

            root = etree.fromstring(payload, parser=parser)

            return etree.tostring(root, encoding="unicode", pretty_print=True).rstrip()
        except (etree.XMLSyntaxError, ValueError):
            return payload.decode("utf-8", errors="replace")
