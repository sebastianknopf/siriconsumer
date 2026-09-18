from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from lxml import etree

from siriconsumer.domain.models import SubscriptionCreate, SubscriptionRecord
from siriconsumer.infrastructure.xml_codec import (
    SIRI_NS,
    first_datetime,
    first_text,
    local_name,
    parse_xml,
    xml_bytes,
)
from siriconsumer.interfaces.intf_profile import (
    CommunicationProfile,
    InboundMessageType,
    ParsedInboundMessage,
    PublisherAction,
)
from siriconsumer.interfaces.intf_siri_client import ProviderStatus

NSMAP = {None: SIRI_NS}

SERVICE_ELEMENTS: dict[str, tuple[str, str]] = {
    "VM": ("VehicleMonitoringSubscriptionRequest", "VehicleMonitoringRequest"),
    "SM": ("StopMonitoringSubscriptionRequest", "StopMonitoringRequest"),
    "SX": ("SituationExchangeSubscriptionRequest", "SituationExchangeRequest"),
    "ET": ("EstimatedTimetableSubscriptionRequest", "EstimatedTimetableRequest"),
    "ST": ("StopTimetableSubscriptionRequest", "StopTimetableRequest"),
    "PT": ("ProductionTimetableSubscriptionRequest", "ProductionTimetableRequest"),
    "FM": ("FacilityMonitoringSubscriptionRequest", "FacilityMonitoringRequest"),
}


class DefaultSiriProfile(CommunicationProfile):
    profile_id = "default"
    version = "default"
    specification = "Standard SIRI common profile"
    supported_services = tuple(SERVICE_ELEMENTS)
    supported_parameters: dict[str, tuple[str, ...]] = {}
    fetched_delivery_message_name = "DataSupplyResponse"

    def validate_subscription(self, config: SubscriptionCreate) -> None:
        return None

    def resolve_endpoint(
        self, action: PublisherAction, subscription: SubscriptionRecord
    ) -> str:
        return str(subscription.config.provider_url)

    def build_subscription_request(self, subscription: SubscriptionRecord) -> bytes:
        config = subscription.config
        service_code = config.service.upper()
        subscription_element, request_element = SERVICE_ELEMENTS.get(
            service_code,
            (f"{config.service}SubscriptionRequest", f"{config.service}Request"),
        )

        root = etree.Element(f"{{{SIRI_NS}}}Siri", nsmap=NSMAP)
        request = etree.SubElement(root, f"{{{SIRI_NS}}}SubscriptionRequest")
        etree.SubElement(request, f"{{{SIRI_NS}}}RequestTimestamp").text = self._timestamp()
        etree.SubElement(request, f"{{{SIRI_NS}}}RequestorRef").text = config.requestor_ref
        etree.SubElement(request, f"{{{SIRI_NS}}}SubscriberRef").text = config.subscriber_ref
        if config.consumer_address is not None:
            etree.SubElement(request, f"{{{SIRI_NS}}}ConsumerAddress").text = str(
                config.consumer_address
            )

        if config.heartbeat.enabled:
            subscription_context = etree.SubElement(
                request, f"{{{SIRI_NS}}}SubscriptionContext"
            )
            etree.SubElement(
                subscription_context, f"{{{SIRI_NS}}}HeartbeatInterval"
            ).text = config.heartbeat.interval

        subscription_request = etree.SubElement(
            request, f"{{{SIRI_NS}}}{subscription_element}"
        )
        service_request = etree.SubElement(
            subscription_request, f"{{{SIRI_NS}}}{request_element}"
        )

        for line in config.filters.lines:
            etree.SubElement(service_request, f"{{{SIRI_NS}}}LineRef").text = line
        for operator in config.filters.operators:
            etree.SubElement(service_request, f"{{{SIRI_NS}}}OperatorRef").text = operator

        if config.request_timestamp is not None:
            etree.SubElement(service_request, f"{{{SIRI_NS}}}RequestTimestamp").text = (
                config.request_timestamp.isoformat()
            )
        if config.preview_interval is not None:
            etree.SubElement(service_request, f"{{{SIRI_NS}}}PreviewInterval").text = (
                config.preview_interval
            )

        etree.SubElement(
            subscription_request, f"{{{SIRI_NS}}}SubscriptionIdentifier"
        ).text = config.subscription_ref

        if config.initial_termination_time is not None:
            etree.SubElement(
                subscription_request, f"{{{SIRI_NS}}}InitialTerminationTime"
            ).text = config.initial_termination_time.isoformat()
        if config.subscription_policy.update_interval:
            etree.SubElement(subscription_request, f"{{{SIRI_NS}}}UpdateInterval").text = (
                config.subscription_policy.update_interval
            )
        if config.incremental_updates:
            etree.SubElement(
                subscription_request, f"{{{SIRI_NS}}}IncrementalUpdates"
            ).text = "true"
        if config.change_before_updates:
            etree.SubElement(
                subscription_request, f"{{{SIRI_NS}}}ChangeBeforeUpdates"
            ).text = config.change_before_updates

        return xml_bytes(root)

    def build_termination_request(self, subscription: SubscriptionRecord) -> bytes:
        root = etree.Element(f"{{{SIRI_NS}}}Siri", nsmap=NSMAP)
        request = etree.SubElement(root, f"{{{SIRI_NS}}}TerminateSubscriptionRequest")
        etree.SubElement(request, f"{{{SIRI_NS}}}RequestTimestamp").text = self._timestamp()
        etree.SubElement(request, f"{{{SIRI_NS}}}RequestorRef").text = (
            subscription.config.requestor_ref
        )
        etree.SubElement(request, f"{{{SIRI_NS}}}SubscriberRef").text = (
            subscription.config.subscriber_ref
        )
        etree.SubElement(request, f"{{{SIRI_NS}}}SubscriptionRef").text = (
            subscription.config.subscription_ref
        )
        return xml_bytes(root)

    def build_check_status_request(self, subscription: SubscriptionRecord) -> bytes:
        root = etree.Element(f"{{{SIRI_NS}}}Siri", nsmap=NSMAP)
        request = etree.SubElement(root, f"{{{SIRI_NS}}}CheckStatusRequest")
        etree.SubElement(request, f"{{{SIRI_NS}}}RequestTimestamp").text = self._timestamp()
        etree.SubElement(request, f"{{{SIRI_NS}}}RequestorRef").text = (
            subscription.config.requestor_ref
        )
        return xml_bytes(root)

    def build_data_supply_request(self, subscription: SubscriptionRecord) -> bytes:
        root = etree.Element(f"{{{SIRI_NS}}}Siri", nsmap=NSMAP)
        request = etree.SubElement(root, f"{{{SIRI_NS}}}DataSupplyRequest")
        etree.SubElement(request, f"{{{SIRI_NS}}}RequestTimestamp").text = self._timestamp()
        etree.SubElement(request, f"{{{SIRI_NS}}}RequestorRef").text = (
            subscription.config.requestor_ref
        )
        etree.SubElement(request, f"{{{SIRI_NS}}}SubscriberRef").text = (
            subscription.config.subscriber_ref
        )
        etree.SubElement(request, f"{{{SIRI_NS}}}SubscriptionRef").text = (
            subscription.config.subscription_ref
        )
        return xml_bytes(root)

    def validate_subscription_response(self, payload: bytes) -> None:
        root = parse_xml(payload)
        status = first_text(root, "Status")
        if status is not None and status.lower() in {"false", "0"}:
            description = first_text(root, "Description") or (
                "Publisher returned a negative SIRI status"
            )
            raise RuntimeError(description)

    def parse_provider_status(self, payload: bytes) -> ProviderStatus:
        root = parse_xml(payload)
        status_text = first_text(root, "Status")
        healthy = status_text is None or status_text.lower() in {"true", "1"}
        return ProviderStatus(
            healthy=healthy,
            service_started_time=first_datetime(root, "ServiceStartedTime"),
        )

    def has_more_data(self, payload: bytes) -> bool:
        root = parse_xml(payload)
        value = first_text(root, "MoreData")
        return value is not None and value.strip().lower() in {"true", "1"}

    def parse_inbound(self, payload: bytes, path: str | None = None) -> ParsedInboundMessage:
        root = parse_xml(payload)
        root_name = local_name(root)
        child_names = [local_name(child) for child in root.iter()]
        subscription_ref = first_text(root, "SubscriptionRef") or first_text(
            root, "SubscriptionIdentifier"
        )

        if "DataReadyNotification" in child_names:
            return ParsedInboundMessage(
                InboundMessageType.DATA_READY,
                subscription_ref=subscription_ref,
                message_name="DataReadyNotification",
            )

        if "HeartbeatNotification" in child_names or root_name == "HeartbeatNotification":
            return ParsedInboundMessage(
                InboundMessageType.HEARTBEAT,
                subscription_ref=subscription_ref,
                service_started_time=first_datetime(root, "ServiceStartedTime"),
                message_name="HeartbeatNotification",
            )

        if "ServiceDelivery" in child_names or root_name == "ServiceDelivery":
            return ParsedInboundMessage(
                InboundMessageType.DELIVERY,
                subscription_ref=subscription_ref,
                message_name="ServiceDelivery",
            )

        raise ValueError("Unsupported SIRI message type")

    def build_inbound_response(
        self,
        message: ParsedInboundMessage,
        subscriptions: Sequence[SubscriptionRecord] = (),
    ) -> bytes:
        names = {
            InboundMessageType.DATA_READY: "DataReadyAcknowledgement",
            InboundMessageType.HEARTBEAT: "HeartbeatResponse",
            InboundMessageType.DELIVERY: "ServiceDeliveryResponse",
        }
        try:
            name = names[message.message_type]
        except KeyError as exc:
            raise ValueError(f"Unsupported inbound message type {message.message_type}") from exc

        root = etree.Element("Siri")
        response = etree.SubElement(root, name)
        etree.SubElement(response, "Status").text = "true"
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8")

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
