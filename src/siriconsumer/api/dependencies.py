from __future__ import annotations

from dataclasses import dataclass

from siriconsumer.infrastructure.file_spool import FileDurableSpool
from siriconsumer.infrastructure.siri_http_client import SiriHttpClient
from siriconsumer.infrastructure.sqlite_repository import SqliteSubscriptionRepository
from siriconsumer.services.delivery_service import DeliveryService
from siriconsumer.services.fetched_delivery_service import FetchedDeliveryService
from siriconsumer.services.provider_monitor import ProviderMonitor
from siriconsumer.services.sink_worker import SinkWorkerPool
from siriconsumer.services.subscription_manager import SubscriptionManager
from siriconsumer.sinks.factory import DefaultSinkFactory


@dataclass(slots=True)
class AppServices:
    repository: SqliteSubscriptionRepository
    siri_client: SiriHttpClient
    spool: FileDurableSpool
    sink_factory: DefaultSinkFactory
    subscription_manager: SubscriptionManager
    delivery_service: DeliveryService
    fetched_delivery_service: FetchedDeliveryService
    provider_monitor: ProviderMonitor
    sink_workers: SinkWorkerPool
