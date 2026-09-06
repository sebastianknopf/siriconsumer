from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from siriconsumer.config import Settings
from siriconsumer.domain.enums import SubscriptionStatus
from siriconsumer.interfaces.intf_siri_client import SiriClient
from siriconsumer.interfaces.intf_subscription_repository import SubscriptionRepository
from siriconsumer.services.subscription_manager import SubscriptionManager

logger = logging.getLogger(__name__)


class ProviderMonitor:
    def __init__(
        self,
        settings: Settings,
        repository: SubscriptionRepository,
        siri_client: SiriClient,
        subscription_manager: SubscriptionManager,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._siri_client = siri_client
        self._subscription_manager = subscription_manager
        self._task: asyncio.Task[None] | None = None
        self._provider_recovery_locks: dict[str, asyncio.Lock] = {}

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="provider-monitor")

    async def stop(self) -> None:
        if self._task is None:
            return

        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)

        self._task = None

    async def record_heartbeat(
        self, subscription_ref: str | None, service_started_time: datetime | None
    ) -> None:
        if subscription_ref is None:
            return

        record = await self._repository.get_by_ref(subscription_ref)
        if record is None:
            logger.warning("Received heartbeat for unknown subscription_ref=%s", subscription_ref)
            return

        now = datetime.now(timezone.utc)
        restart_detected = (
            service_started_time is not None
            and record.last_service_started_time is not None
            and service_started_time != record.last_service_started_time
        )

        record.last_heartbeat_at = now
        if service_started_time is not None:
            record.last_service_started_time = service_started_time

        await self._repository.save(record)

        if restart_detected:
            await self._recover_provider_once(str(record.config.provider_url))

    async def _run(self) -> None:
        while True:
            try:
                await self._check_all_providers()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Provider monitor iteration failed")

            await asyncio.sleep(self._settings.provider_check_interval_seconds)

    async def _check_all_providers(self) -> None:
        subscriptions = await self._repository.list_all()
        providers: dict[str, list] = {}
        for record in subscriptions:
            if record.status is SubscriptionStatus.TERMINATED:
                continue

            providers.setdefault(str(record.config.provider_url), []).append(record)

        for provider_url, records in providers.items():
            representative = records[0]
            if not representative.config.heartbeat.active_check_enabled:
                await self._check_heartbeat_timeouts(records)
                continue

            try:
                status = await self._siri_client.check_status(
                    provider_url, representative.config.requestor_ref
                )
            except Exception:
                logger.warning("Active publisher status check failed provider=%s", provider_url, exc_info=True)
                await self._check_heartbeat_timeouts(records)
                continue

            restart_detected = False
            for record in records:
                if status.service_started_time is not None:
                    if (
                        record.last_service_started_time is not None
                        and record.last_service_started_time != status.service_started_time
                    ):
                        restart_detected = True

                    record.last_service_started_time = status.service_started_time
                    await self._repository.save(record)
            if restart_detected:
                await self._recover_provider_once(provider_url)

    async def _check_heartbeat_timeouts(self, records: list) -> None:
        now = datetime.now(timezone.utc)
        for record in records:
            if not record.config.heartbeat.enabled or record.last_heartbeat_at is None:
                continue

            age = (now - record.last_heartbeat_at).total_seconds()
            if age > record.config.heartbeat.timeout_seconds:
                logger.warning(
                    "Heartbeat timeout provider=%s subscription_id=%s age_seconds=%.1f",
                    record.config.provider_url,
                    record.id,
                    age,
                )

                await self._recover_provider_once(str(record.config.provider_url))

                return

    async def _recover_provider_once(self, provider_url: str) -> None:
        lock = self._provider_recovery_locks.setdefault(provider_url, asyncio.Lock())
        if lock.locked():
            return

        async with lock:
            logger.warning("Publisher restart detected; recovering provider=%s", provider_url)
            await self._subscription_manager.recover_provider(provider_url)
