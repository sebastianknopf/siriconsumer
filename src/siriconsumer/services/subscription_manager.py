from __future__ import annotations

import asyncio
import logging

from siriconsumer.domain.enums import SubscriptionStatus
from siriconsumer.domain.models import SubscriptionCreate, SubscriptionRecord
from siriconsumer.interfaces.intf_delivery_admission import DeliveryAdmission
from siriconsumer.interfaces.intf_sink_factory import SinkFactory
from siriconsumer.interfaces.intf_siri_client import SiriClient
from siriconsumer.interfaces.intf_spool import DurableSpool
from siriconsumer.profiles.registry import ProfileRegistry
from siriconsumer.interfaces.intf_subscription_repository import (
    SubscriptionRepository,
    SubscriptionRoutingConflictError,
)

logger = logging.getLogger(__name__)


class SubscriptionManager:
    def __init__(
        self,
        repository: SubscriptionRepository,
        siri_client: SiriClient,
        spool: DurableSpool,
        sink_factory: SinkFactory,
        delivery_admission: DeliveryAdmission,
        profile_registry: ProfileRegistry | None = None,
    ) -> None:
        self._repository = repository
        self._siri_client = siri_client
        self._spool = spool
        self._sink_factory = sink_factory
        self._delivery_admission = delivery_admission
        self._profile_registry = profile_registry or ProfileRegistry()
        self._locks: dict[str, asyncio.Lock] = {}

    async def create(self, config: SubscriptionCreate) -> SubscriptionRecord:
        self._profile_registry.get(config.profile, config.version).validate_subscription(config)

        if config.profile == "de-vdv":
            assert config.producer_ref is not None
            route_key = f"vdv-route:{config.producer_ref}:{self._service_key(config.service)}"
            async with self._lock(route_key):
                await self._validate_vdv_route(config)
                return await self._create_and_activate(config)

        return await self._create_and_activate(config)

    async def _create_and_activate(self, config: SubscriptionCreate) -> SubscriptionRecord:
        record = await self._repository.create(config)
        await self._delivery_admission.reopen(config.subscription_ref)
        await self._activate(record)
        return await self._require(config.subscription_ref)

    async def _validate_vdv_route(self, config: SubscriptionCreate) -> None:
        assert config.producer_ref is not None
        existing = await self._repository.list_by_producer_service(
            config.producer_ref, config.service
        )
        conflicting = [
            record
            for record in existing
            if record.config.profile == "de-vdv"
            and (record.config.profile, record.config.version)
            != (config.profile, config.version)
        ]
        if conflicting:
            current = conflicting[0].config
            raise SubscriptionRoutingConflictError(
                "VDV inbound endpoint "
                f"({config.producer_ref}, {self._service_key(config.service)}) is already bound "
                f"to profile '{current.profile}' version '{current.version}'"
            )

    @staticmethod
    def _service_key(service: str) -> str:
        return service.strip().upper().replace("_", "-")

    async def terminate(
        self, subscription_ref: str, *, force: bool = False, spool: bool = True
    ) -> None:
        record = await self._require(subscription_ref)
        async with self._lock(subscription_ref):
            # Establish the local cut-off before telling the publisher to terminate.
            # Requests that already own a delivery lease may still finish; requests
            # arriving after this point are rejected before they can enter the spool.
            await self._delivery_admission.close(subscription_ref)
            await self._repository.update_status(
                subscription_ref, SubscriptionStatus.TERMINATING
            )

            if force:
                try:
                    await self._siri_client.terminate(record)
                except Exception:
                    logger.warning(
                        "Publisher termination failed during force termination; "
                        "continuing with local drain and deletion subscription_ref=%s "
                        "previous_status=%s previous_error=%s",
                        subscription_ref,
                        record.status.value,
                        record.last_error,
                        exc_info=True,
                    )
            else:
                try:
                    await self._siri_client.terminate(record)
                except Exception as exc:
                    await self._repository.update_status(
                        subscription_ref, SubscriptionStatus.FAILED, str(exc)
                    )

                    await self._delivery_admission.reopen(subscription_ref)
                    raise

            # Any DirectDelivery request admitted before the cut-off is allowed to
            # finish. If it was throttled when termination started, its normal HTTP
            # throttle timeout is disabled so it can persist as the sink drains.
            await self._delivery_admission.wait_until_drained(subscription_ref)

            # No new inbound DirectDelivery can enter the spool now. By default,
            # drain every accepted message through the configured sink. When spool
            # processing is disabled for termination, discard entries that are not
            # already owned by a sink worker and let the in-flight entry finish.
            if spool:
                await self._spool.wait_until_empty(subscription_ref)
            else:
                purged = await self._spool.purge(subscription_ref)
                await self._spool.wait_until_idle(subscription_ref)
                logger.info(
                    "Discarded pending spool entries during termination "
                    "subscription_ref=%s purged=%s",
                    subscription_ref,
                    purged,
                )

            await self._repository.delete(subscription_ref)
            # The temporary 410 termination window ends exactly when durable
            # subscription state is removed. Later callbacks are unknown and must
            # therefore be reported as HTTP 404 until the same ref is recreated.
            await self._delivery_admission.mark_deleted(subscription_ref)

            try:
                await self._sink_factory.remove(subscription_ref)
            except Exception:
                logger.warning(
                    "Failed to close sink after subscription deletion subscription_ref=%s",
                    subscription_ref,
                    exc_info=True,
                )

            logger.info(
                "Subscription terminated and deleted subscription_ref=%s spool=%s",
                subscription_ref,
                spool,
            )

    async def recover(self, subscription_ref: str) -> SubscriptionRecord:
        record = await self._require(subscription_ref)
        async with self._lock(subscription_ref):
            await self._recover_locked(record)

        return await self._require(subscription_ref)

    async def recover_all_startup(self) -> None:
        for record in await self._repository.list_recoverable():
            subscription_ref = record.config.subscription_ref
            try:
                await self.recover(subscription_ref)
            except Exception:
                logger.exception("Startup recovery failed subscription_ref=%s", subscription_ref)

    async def recover_provider(self, provider_url: str) -> None:
        records = await self._repository.list_by_provider(provider_url)
        for record in records:
            subscription_ref = record.config.subscription_ref
            try:
                await self.recover(subscription_ref)
            except Exception:
                logger.exception(
                    "Provider recovery failed provider=%s subscription_ref=%s",
                    provider_url,
                    subscription_ref,
                )

    async def _activate(self, record: SubscriptionRecord) -> None:
        subscription_ref = record.config.subscription_ref
        async with self._lock(subscription_ref):
            try:
                await self._repository.update_status(subscription_ref, SubscriptionStatus.CREATING)
                current = await self._require(subscription_ref)
                await self._siri_client.subscribe(current)
                await self._repository.update_status(subscription_ref, SubscriptionStatus.ACTIVE)
            except Exception as exc:
                await self._repository.update_status(subscription_ref, SubscriptionStatus.FAILED, str(exc))
                raise

    async def _recover_locked(self, record: SubscriptionRecord) -> None:
        subscription_ref = record.config.subscription_ref
        await self._repository.update_status(subscription_ref, SubscriptionStatus.DEGRADED)
        try:
            try:
                await self._siri_client.terminate(record)
            except Exception:
                logger.warning(
                    "Old subscription termination failed during recovery; continuing subscription_ref=%s",
                    subscription_ref,
                    exc_info=True,
                )

            current = await self._require(subscription_ref)
            await self._repository.update_status(subscription_ref, SubscriptionStatus.CREATING)
            await self._siri_client.subscribe(current)
            await self._repository.update_status(subscription_ref, SubscriptionStatus.ACTIVE)
        except Exception as exc:
            await self._repository.update_status(subscription_ref, SubscriptionStatus.FAILED, str(exc))
            raise

    async def _require(self, subscription_ref: str) -> SubscriptionRecord:
        record = await self._repository.get(subscription_ref)
        if record is None:
            raise KeyError(subscription_ref)
        return record

    def _lock(self, subscription_ref: str) -> asyncio.Lock:
        return self._locks.setdefault(subscription_ref, asyncio.Lock())
