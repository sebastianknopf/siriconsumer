from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, Sequence

from siriconsumer.domain.models import SubscriptionCreate, SubscriptionRecord
from siriconsumer.interfaces.intf_siri_client import ProviderStatus


class PublisherAction(StrEnum):
    SUBSCRIBE = "subscribe"
    TERMINATE = "terminate"
    CHECK_STATUS = "check_status"
    FETCH_DELIVERY = "fetch_delivery"


class InboundMessageType(StrEnum):
    DELIVERY = "delivery"
    DATA_READY = "data_ready"
    HEARTBEAT = "heartbeat"
    CLIENT_STATUS = "client_status"


@dataclass(slots=True)
class ParsedInboundMessage:
    message_type: InboundMessageType
    subscription_ref: str | None = None
    service_started_time: datetime | None = None
    service: str | None = None
    producer_ref: str | None = None
    message_name: str | None = None
    include_active_subscriptions: bool = False


class CommunicationProfile(Protocol):
    profile_id: str
    version: str
    specification: str
    supported_services: tuple[str, ...]
    supported_parameters: dict[str, tuple[str, ...]]
    fetched_delivery_message_name: str

    def validate_subscription(self, config: SubscriptionCreate) -> None: ...

    def resolve_endpoint(
        self, action: PublisherAction, subscription: SubscriptionRecord
    ) -> str: ...

    def build_subscription_request(self, subscription: SubscriptionRecord) -> bytes: ...

    def build_termination_request(self, subscription: SubscriptionRecord) -> bytes: ...

    def build_check_status_request(self, subscription: SubscriptionRecord) -> bytes: ...

    def build_data_supply_request(self, subscription: SubscriptionRecord) -> bytes: ...

    def validate_subscription_response(self, payload: bytes) -> None: ...

    def parse_provider_status(self, payload: bytes) -> ProviderStatus: ...

    def has_more_data(self, payload: bytes) -> bool: ...

    def parse_inbound(self, payload: bytes, path: str | None = None) -> ParsedInboundMessage: ...

    def build_inbound_response(
        self,
        message: ParsedInboundMessage,
        subscriptions: Sequence[SubscriptionRecord] = (),
    ) -> bytes: ...
