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
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(self._rebuild_index)

        for subscription_ref, queue in self._index.items():
            for entry in queue:
                self._active_ids.add(entry.metadata.message_id)

            self._schedule_head(subscription_ref)

    async def put(self, metadata: SpoolMetadata, payload: bytes) -> SpoolEntry:
        async with self._lock:
            queue = self._index[metadata.subscription_ref]

            while len(queue) >= self._max:
                oldest_index = next(
                    (
                        i
                        for i, item in enumerate(queue)
                        if item.metadata.message_id not in self._inflight_ids
                    ),
                    0,
                )
                oldest = queue[oldest_index]
                del queue[oldest_index]

                self._active_ids.discard(oldest.metadata.message_id)
                if oldest_index == 0:
                    self._scheduled_subscriptions.discard(metadata.subscription_ref)
                await asyncio.to_thread(self._delete_files, oldest)

                logger.warning(
                    "Spool limit reached; dropped oldest pending message "
                    "subscription_ref=%s message_id=%s",
                    metadata.subscription_ref,
                    oldest.metadata.message_id,
                )

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
            queue.append(entry)

            self._active_ids.add(metadata.message_id)
            self._schedule_head(metadata.subscription_ref)

            return entry

    async def remove(self, entry: SpoolEntry) -> None:
        async with self._lock:
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

            await asyncio.to_thread(self._delete_files, entry)

            self._schedule_head(subscription_ref)

    async def purge(self, subscription_ref: str) -> int:
        """Remove every queued or in-flight spool entry for a subscription.

        An already executing sink write cannot be undone, but the entry is removed
        from the active index so it can never be requeued or delivered again.
        """
        async with self._lock:
            queue = self._index.pop(subscription_ref, deque())
            entries = list(queue)

            self._scheduled_subscriptions.discard(subscription_ref)
            self._inflight_subscriptions.discard(subscription_ref)

            for entry in entries:
                self._active_ids.discard(entry.metadata.message_id)
                self._inflight_ids.discard(entry.metadata.message_id)

            for entry in entries:
                await asyncio.to_thread(self._delete_files, entry)

            return len(entries)

    async def next_pending(self) -> SpoolEntry:
        while True:
            entry = await self._ready.get()
            async with self._lock:
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

                return entry

    async def requeue(self, entry: SpoolEntry) -> None:
        async with self._lock:
            subscription_ref = entry.metadata.subscription_ref
            self._inflight_ids.discard(entry.metadata.message_id)
            self._inflight_subscriptions.discard(subscription_ref)
            if entry.metadata.message_id in self._active_ids:
                self._schedule_head(subscription_ref)

    def pending_count(self, subscription_ref: str) -> int:
        queue = self._index.get(subscription_ref)

        return len(queue) if queue is not None else 0

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

            while len(self._index[subscription_ref]) > self._max:
                oldest = self._index[subscription_ref].popleft()

                self._delete_files(oldest)

                logger.warning(
                    "Dropped excess startup spool entry subscription_ref=%s message_id=%s",
                    subscription_ref,
                    oldest.metadata.message_id,
                )

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
