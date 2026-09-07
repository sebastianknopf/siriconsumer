from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque
from urllib.parse import quote
from uuid import UUID

from siriconsumer.domain.models import SpoolEntry, SpoolMetadata
from siriconsumer.interfaces.intf_spool import SpoolCapacityTimeoutError

logger = logging.getLogger(__name__)


class FileDurableSpool:
    def __init__(self, root: Path, max_messages_per_subscription: int = 100) -> None:
        self._root = root
        self._max = max_messages_per_subscription
        self._index: dict[str, Deque[SpoolEntry]] = defaultdict(deque)
        self._ready: asyncio.Queue[SpoolEntry] = asyncio.Queue()
        self._active_ids: set[UUID] = set()
        self._inflight_ids: set[UUID] = set()
        self._inflight_subscriptions: set[str] = set()
        self._scheduled_subscriptions: set[str] = set()
        self._idle_events: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._capacity_changed = asyncio.Condition(self._lock)

    async def initialize(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(self._rebuild_index)

        for subscription_ref, queue in self._index.items():
            for entry in queue:
                self._active_ids.add(entry.metadata.message_id)

            self._schedule_head(subscription_ref)

    async def put(
        self,
        metadata: SpoolMetadata,
        payload: bytes,
        *,
        wait_timeout_seconds: float | None = None,
    ) -> SpoolEntry:
        async with self._capacity_changed:
            try:
                if wait_timeout_seconds is None:
                    await self._capacity_changed.wait_for(
                        lambda: self._has_capacity_locked(metadata.subscription_ref)
                    )
                else:
                    async with asyncio.timeout(wait_timeout_seconds):
                        await self._capacity_changed.wait_for(
                            lambda: self._has_capacity_locked(metadata.subscription_ref)
                        )
            except TimeoutError as exc:
                raise SpoolCapacityTimeoutError(
                    f"Spool capacity timeout for subscription_ref={metadata.subscription_ref}"
                ) from exc

            subscription_dir = self._root / quote(metadata.subscription_ref, safe="")
            subscription_dir.mkdir(parents=True, exist_ok=True)

            stem = f"{metadata.received_at.strftime('%Y%m%dT%H%M%S.%fZ')}_{metadata.message_id}"
            payload_path = subscription_dir / f"{stem}.payload"
            metadata_path = subscription_dir / f"{stem}.json"

            await asyncio.to_thread(self._atomic_write_bytes, payload_path, payload)
            await asyncio.to_thread(
                self._atomic_write_text, metadata_path, metadata.model_dump_json()
            )

            entry = SpoolEntry(
                metadata=metadata, payload_path=payload_path, metadata_path=metadata_path
            )
            self._index[metadata.subscription_ref].append(entry)

            self._active_ids.add(metadata.message_id)
            self._schedule_head(metadata.subscription_ref)

            return entry

    async def remove(self, entry: SpoolEntry) -> None:
        async with self._capacity_changed:
            subscription_ref = entry.metadata.subscription_ref
            queue = self._index.get(subscription_ref)
            if queue is not None:
                try:
                    queue.remove(entry)
                except ValueError:
                    pass
                if not queue:
                    self._index.pop(subscription_ref, None)

            self._active_ids.discard(entry.metadata.message_id)
            self._inflight_ids.discard(entry.metadata.message_id)
            self._inflight_subscriptions.discard(subscription_ref)
            self._mark_idle_if_needed(subscription_ref)

            await asyncio.to_thread(self._delete_files, entry)

            self._schedule_head(subscription_ref)
            self._capacity_changed.notify_all()

    async def purge(self, subscription_ref: str) -> int:
        """Remove queued entries while preserving any entry currently owned by a sink worker."""
        async with self._capacity_changed:
            queue = self._index.get(subscription_ref, deque())
            removable = [
                entry
                for entry in queue
                if entry.metadata.message_id not in self._inflight_ids
            ]

            for entry in removable:
                try:
                    queue.remove(entry)
                except ValueError:
                    continue
                self._active_ids.discard(entry.metadata.message_id)
                await asyncio.to_thread(self._delete_files, entry)

            self._scheduled_subscriptions.discard(subscription_ref)
            if not queue:
                self._index.pop(subscription_ref, None)

            if removable:
                self._capacity_changed.notify_all()

            return len(removable)

    async def wait_until_idle(self, subscription_ref: str) -> None:
        while True:
            async with self._lock:
                if subscription_ref not in self._inflight_subscriptions:
                    return
                event = self._idle_events.setdefault(subscription_ref, asyncio.Event())
                event.clear()

            await event.wait()

    async def next_pending(self) -> SpoolEntry:
        while True:
            entry = await self._ready.get()
            async with self._capacity_changed:
                subscription_ref = entry.metadata.subscription_ref
                queue = self._index.get(subscription_ref)
                if entry.metadata.message_id not in self._active_ids:
                    continue
                if queue is None or not queue:
                    continue
                if queue[0].metadata.message_id != entry.metadata.message_id:
                    continue
                if subscription_ref in self._inflight_subscriptions:
                    continue

                self._scheduled_subscriptions.discard(subscription_ref)
                self._inflight_subscriptions.add(subscription_ref)
                self._inflight_ids.add(entry.metadata.message_id)
                self._idle_events.setdefault(subscription_ref, asyncio.Event()).clear()
                self._capacity_changed.notify_all()

                return entry

    async def requeue(self, entry: SpoolEntry) -> None:
        async with self._lock:
            subscription_ref = entry.metadata.subscription_ref
            self._inflight_ids.discard(entry.metadata.message_id)
            self._inflight_subscriptions.discard(subscription_ref)
            self._mark_idle_if_needed(subscription_ref)
            if entry.metadata.message_id in self._active_ids:
                self._schedule_head(subscription_ref)

    async def record_retry(self, entry: SpoolEntry) -> int:
        async with self._lock:
            if entry.metadata.message_id not in self._inflight_ids:
                raise RuntimeError("Cannot record a retry for an entry that is not in flight")
            entry.metadata.retry_count += 1
            await asyncio.to_thread(
                self._atomic_write_text,
                entry.metadata_path,
                entry.metadata.model_dump_json(),
            )

            return entry.metadata.retry_count

    def pending_count(self, subscription_ref: str) -> int:
        queue = self._index.get(subscription_ref)

        return len(queue) if queue is not None else 0

    def _has_capacity_locked(self, subscription_ref: str) -> bool:
        queue = self._index.get(subscription_ref)
        if not queue:
            return True

        return self._pending_count_locked(queue) < self._max

    def _pending_count_locked(self, queue: Deque[SpoolEntry]) -> int:
        if not queue:
            return 0
        subscription_ref = queue[0].metadata.subscription_ref

        return len(queue) - (1 if subscription_ref in self._inflight_subscriptions else 0)

    def _mark_idle_if_needed(self, subscription_ref: str) -> None:
        if subscription_ref in self._inflight_subscriptions:
            return

        event = self._idle_events.get(subscription_ref)
        if event is not None:
            event.set()

    def _schedule_head(self, subscription_ref: str) -> None:
        if subscription_ref in self._inflight_subscriptions:
            return
        if subscription_ref in self._scheduled_subscriptions:
            return
        queue = self._index.get(subscription_ref)
        if not queue:
            return

        entry = queue[0]
        if entry.metadata.message_id not in self._active_ids:
            return

        self._scheduled_subscriptions.add(subscription_ref)
        self._ready.put_nowait(entry)

    def _rebuild_index(self) -> None:
        for metadata_path in self._root.glob("*/*.json"):
            try:
                data = json.loads(metadata_path.read_text())
                metadata = SpoolMetadata.model_validate(data)
                payload_path = metadata_path.with_suffix(".payload")

                if not payload_path.exists():
                    logger.warning("Ignoring spool metadata without payload: %s", metadata_path)
                    continue

                self._index[metadata.subscription_ref].append(
                    SpoolEntry(
                        metadata=metadata, payload_path=payload_path, metadata_path=metadata_path
                    )
                )
            except Exception:
                logger.exception("Could not reconstruct spool entry from %s", metadata_path)

        for subscription_ref, queue in list(self._index.items()):
            ordered = sorted(queue, key=lambda item: item.metadata.received_at)
            self._index[subscription_ref] = deque(ordered)

    @staticmethod
    def _atomic_write_bytes(path: Path, content: bytes) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_bytes(content)
        temp.replace(path)

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(content)
        temp.replace(path)

    @staticmethod
    def _delete_files(entry: SpoolEntry) -> None:
        entry.payload_path.unlink(missing_ok=True)
        entry.metadata_path.unlink(missing_ok=True)
