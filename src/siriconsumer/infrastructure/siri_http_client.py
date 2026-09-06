from __future__ import annotations

from datetime import datetime, timezone

import logging

import httpx
from lxml import etree

from siriconsumer.domain.enums import DeliveryMode
from siriconsumer.domain.models import SubscriptionRecord
from siriconsumer.infrastructure.xml_codec import SIRI_NS, first_datetime, first_text, parse_xml, xml_bytes
from siriconsumer.interfaces.intf_siri_client import ProviderStatus
from siriconsumer.siri_debug import log_siri_payload

logger = logging.getLogger(__name__)

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

class SiriHttpClient:
    def __init__(
        self, timeout_seconds: float = 20.0, *, debug_siri_logging: bool = False
    ) -> None:
        self._client = httpx.AsyncClient(timeout=timeout_seconds)
        self._debug_siri_logging = debug_siri_logging

    async def close(self) -> None:
        await self._client.aclose()

    async def subscribe(self, subscription: SubscriptionRecord) -> None:
        payload = self._build_subscription_request(subscription)
        response = await self._post(subscription, payload)
        response.raise_for_status()
        self._raise_on_negative_status(response.content)

    async def terminate(self, subscription: SubscriptionRecord) -> None:
        payload = self._build_termination_request(subscription)
        response = await self._post(subscription, payload)
        if response.status_code == 404:
            return
        response.raise_for_status()
        # Termination is deliberately best-effort. Some publishers answer with a
        # negative SIRI status when the old subscription no longer exists.

    async def check_status(self, subscription: SubscriptionRecord) -> ProviderStatus:
        payload = self._build_check_status_request(subscription.config.requestor_ref)
        response = await self._post(subscription, payload)
        response.raise_for_status()
        root = parse_xml(response.content)
        status_text = first_text(root, "Status")
        healthy = status_text is None or status_text.lower() in {"true", "1"}
        return ProviderStatus(
            healthy=healthy,
            service_started_time=first_datetime(root, "ServiceStartedTime"),
        )

    async def fetch_delivery(self, subscription: SubscriptionRecord) -> bytes:
        payload = self._build_data_supply_request(subscription)
        response = await self._post(subscription, payload)
        response.raise_for_status()
        return response.content


    async def _post(self, subscription: SubscriptionRecord, payload: bytes) -> httpx.Response:
        headers = {"Content-Type": "application/xml"}
        for name, value in subscription.config.headers.items():
            for existing_name in list(headers):
                if existing_name.lower() == name.lower():
                    del headers[existing_name]
            headers[name] = value

        endpoint = str(subscription.config.provider_url)
        log_siri_payload(
            logger,
            enabled=self._debug_siri_logging,
            direction="OUTGOING REQUEST",
            payload=payload,
            endpoint=endpoint,
        )

        response = await self._client.post(endpoint, content=payload, headers=headers)
        log_siri_payload(
            logger,
            enabled=self._debug_siri_logging,
            direction=f"INCOMING RESPONSE status={response.status_code}",
            payload=response.content,
            endpoint=endpoint,
        )
        
        return response

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _build_subscription_request(self, subscription: SubscriptionRecord) -> bytes:
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
            etree.SubElement(request, f"{{{SIRI_NS}}}ConsumerAddress").text = str(config.consumer_address)

        if config.heartbeat.enabled:
            subscription_context = etree.SubElement(
                request, f"{{{SIRI_NS}}}SubscriptionContext"
            )
            etree.SubElement(
                subscription_context, f"{{{SIRI_NS}}}HeartbeatInterval"
            ).text = config.heartbeat.interval

        service_request = etree.SubElement(request, f"{{{SIRI_NS}}}{subscription_element}")
        filter_request = etree.SubElement(service_request, f"{{{SIRI_NS}}}{request_element}")
        for line in config.filters.lines:
            etree.SubElement(filter_request, f"{{{SIRI_NS}}}LineRef").text = line
        for operator in config.filters.operators:
            etree.SubElement(filter_request, f"{{{SIRI_NS}}}OperatorRef").text = operator

        etree.SubElement(service_request, f"{{{SIRI_NS}}}SubscriptionIdentifier").text = (
            config.subscription_ref
        )
        if config.initial_termination_time is not None:
            etree.SubElement(service_request, f"{{{SIRI_NS}}}InitialTerminationTime").text = (
                config.initial_termination_time.isoformat()
            )
        if config.subscription_policy.update_interval:
            etree.SubElement(service_request, f"{{{SIRI_NS}}}UpdateInterval").text = (
                config.subscription_policy.update_interval
            )

        return xml_bytes(root)

    def _build_termination_request(self, subscription: SubscriptionRecord) -> bytes:
        root = etree.Element(f"{{{SIRI_NS}}}Siri", nsmap=NSMAP)
        request = etree.SubElement(root, f"{{{SIRI_NS}}}TerminateSubscriptionRequest")
        etree.SubElement(request, f"{{{SIRI_NS}}}RequestTimestamp").text = self._timestamp()
        etree.SubElement(request, f"{{{SIRI_NS}}}RequestorRef").text = subscription.config.requestor_ref
        etree.SubElement(request, f"{{{SIRI_NS}}}SubscriberRef").text = subscription.config.subscriber_ref
        etree.SubElement(request, f"{{{SIRI_NS}}}SubscriptionRef").text = (
            subscription.config.subscription_ref
        )
        return xml_bytes(root)

    def _build_check_status_request(self, requestor_ref: str) -> bytes:
        root = etree.Element(f"{{{SIRI_NS}}}Siri", nsmap=NSMAP)
        request = etree.SubElement(root, f"{{{SIRI_NS}}}CheckStatusRequest")
        etree.SubElement(request, f"{{{SIRI_NS}}}RequestTimestamp").text = self._timestamp()
        etree.SubElement(request, f"{{{SIRI_NS}}}RequestorRef").text = requestor_ref
        return xml_bytes(root)

    def _build_data_supply_request(self, subscription: SubscriptionRecord) -> bytes:
        root = etree.Element(f"{{{SIRI_NS}}}Siri", nsmap=NSMAP)
        request = etree.SubElement(root, f"{{{SIRI_NS}}}DataSupplyRequest")
        etree.SubElement(request, f"{{{SIRI_NS}}}RequestTimestamp").text = self._timestamp()
        etree.SubElement(request, f"{{{SIRI_NS}}}RequestorRef").text = subscription.config.requestor_ref
        etree.SubElement(request, f"{{{SIRI_NS}}}SubscriberRef").text = subscription.config.subscriber_ref
        etree.SubElement(request, f"{{{SIRI_NS}}}SubscriptionRef").text = subscription.config.subscription_ref
        return xml_bytes(root)

    @staticmethod
    def _raise_on_negative_status(payload: bytes) -> None:
        root = parse_xml(payload)
        status = first_text(root, "Status")
        if status is not None and status.lower() in {"false", "0"}:
            description = first_text(root, "Description") or "Publisher returned a negative SIRI status"
            raise RuntimeError(description)
