from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from lxml import etree

from siriconsumer.domain.enums import DeliveryMode, SubscriptionStatus
from siriconsumer.domain.models import SubscriptionCreate, SubscriptionRecord
from siriconsumer.infrastructure.xml_codec import first_datetime, first_text, local_name, parse_xml
from siriconsumer.interfaces.intf_profile import (
    CommunicationProfile,
    InboundMessageType,
    ParsedInboundMessage,
    PublisherAction,
)
from siriconsumer.interfaces.intf_siri_client import ProviderStatus

VDV_453_VERSION = "2.6.1"
VDV_454_VERSION = "2.2.1"
VDV_XSD_VERSION = "V2017e"

SERVICE_ELEMENTS: dict[str, str] = {
    "CT": "AboASBRef",
    "CM": "AboASB",
    "ST": "AboAZBRef",
    "SM": "AboAZB",
    "VM": "AboVIS",
    "PT": "AboAUSRef",
    "ET": "AboAUS",
}

VDV_SERVICE_NAMES: dict[str, str] = {
    "CT": "REF-ANS",
    "CM": "ANS",
    "ST": "REF-DFI",
    "SM": "DFI",
    "VM": "VIS",
    "PT": "REF-AUS",
    "ET": "AUS",
}

SIRI_SERVICE_NAMES: dict[str, str] = {
    vdv_service: siri_service
    for siri_service, vdv_service in VDV_SERVICE_NAMES.items()
}

ACTION_PATHS: dict[PublisherAction, str] = {
    PublisherAction.SUBSCRIBE: "aboverwalten.xml",
    PublisherAction.TERMINATE: "aboverwalten.xml",
    PublisherAction.CHECK_STATUS: "status.xml",
    PublisherAction.FETCH_DELIVERY: "datenabrufen.xml",
}


class GermanVdv2Profile(CommunicationProfile):
    profile_id = "de-vdv"
    version = "2"
    specification = (
        "VDV 453 2.6.1 / VDV 454 2.2.1 using the common V2017e XML schema"
    )
    supported_services = ("CT", "CM", "ST", "SM", "VM", "PT", "ET")
    supported_parameters = {
        "CT": ("asbId",),
        "CM": ("asbId",),
        "ST": ("azbId",),
        "SM": ("azbId",),
        "VM": ("visId",),
        "PT": (),
        "ET": (),
    }
    fetched_delivery_message_name = "DatenAbrufenAntwort"

    def __init__(self) -> None:
        self._service_started_at = self._timestamp()

    def validate_subscription(self, config: SubscriptionCreate) -> None:
        if config.delivery_mode is not DeliveryMode.FETCHED:
            raise ValueError("Profile 'de-vdv' version '2' supports fetched delivery only")

        service = self._service_key(config.service)
        if service not in SERVICE_ELEMENTS:
            raise ValueError(
                "Profile 'de-vdv' version '2' supports SIRI service codes CT, CM, ST, SM, "
                "VM, PT, and ET"
            )

        if not config.producer_ref or not config.producer_ref.strip():
            raise ValueError(
                "Profile 'de-vdv' version '2' requires producer_ref as the producer control-centre identifier"
            )

        if config.initial_termination_time is None:
            raise ValueError(
                "Profile 'de-vdv' version '2' requires initial_termination_time as VDV VerfallZst"
            )

        required_parameter = {
            "CT": "asbId",
            "CM": "asbId",
            "ST": "azbId",
            "SM": "azbId",
            "VM": "visId",
        }.get(service)
        if required_parameter is not None:
            self._parameter(config, required_parameter, required=True)

    def resolve_endpoint(
        self, action: PublisherAction, subscription: SubscriptionRecord
    ) -> str:
        base = str(subscription.config.provider_url).rstrip("/")
        return f"{base}/{ACTION_PATHS[action]}"

    def build_subscription_request(self, subscription: SubscriptionRecord) -> bytes:
        config = subscription.config
        service_element = SERVICE_ELEMENTS[self._service_key(config.service)]

        if config.initial_termination_time is None:
            raise ValueError("VDV subscriptions require initial_termination_time")

        root = etree.Element(
            "AboAnfrage",
            Sender=config.requestor_ref,
            Zst=self._timestamp(),
        )
        request = etree.SubElement(
            root,
            service_element,
            AboID=config.subscription_ref,
            VerfallZst=config.initial_termination_time.isoformat(),
        )

        self._build_service_subscription(request, config)
        return self._xml_bytes(root)

    def build_termination_request(self, subscription: SubscriptionRecord) -> bytes:
        root = etree.Element(
            "AboAnfrage",
            Sender=subscription.config.requestor_ref,
            Zst=self._timestamp(),
        )
        etree.SubElement(root, "AboLoeschen").text = subscription.config.subscription_ref
        return self._xml_bytes(root)

    def build_check_status_request(self, subscription: SubscriptionRecord) -> bytes:
        root = etree.Element(
            "StatusAnfrage",
            Sender=subscription.config.requestor_ref,
            Zst=self._timestamp(),
        )
        return self._xml_bytes(root)

    def build_data_supply_request(self, subscription: SubscriptionRecord) -> bytes:
        root = etree.Element(
            "DatenAbrufenAnfrage",
            Sender=subscription.config.requestor_ref,
            Zst=self._timestamp(),
        )
        return self._xml_bytes(root)

    def validate_subscription_response(self, payload: bytes) -> None:
        root = parse_xml(payload)
        if local_name(root) != "AboAntwort":
            raise RuntimeError(f"Expected AboAntwort, received {local_name(root)}")

        self._raise_on_negative_confirmation(root)

    def parse_provider_status(self, payload: bytes) -> ProviderStatus:
        root = parse_xml(payload)
        if local_name(root) != "StatusAntwort":
            raise RuntimeError(f"Expected StatusAntwort, received {local_name(root)}")

        status_nodes = root.xpath("//*[local-name()='Status']")
        healthy = False
        if status_nodes:
            result = status_nodes[0].get("Ergebnis")
            healthy = result is not None and result.strip().lower() == "ok"

        return ProviderStatus(
            healthy=healthy,
            service_started_time=first_datetime(root, "StartDienstZst"),
        )

    def has_more_data(self, payload: bytes) -> bool:
        root = parse_xml(payload)
        values = root.xpath("//*[local-name()='WeitereDaten']/text()")
        if values:
            return str(values[0]).strip().lower() in {"true", "1"}

        for element in root.iter():
            value = element.get("WeitereDaten")
            if value is not None:
                return value.strip().lower() in {"true", "1"}

        return False

    def parse_inbound(self, payload: bytes, path: str | None = None) -> ParsedInboundMessage:
        root = parse_xml(payload)
        root_name = local_name(root)
        producer_ref, service = self._route_from_path(path)
        action = self._action_from_path(path)

        expected_action = {
            "DatenBereitAnfrage": "datenbereit.xml",
            "ClientStatusAnfrage": "clientstatus.xml",
        }.get(root_name)
        if expected_action is not None and action != expected_action:
            raise ValueError(
                f"VDV message '{root_name}' must use action path '{expected_action}'"
            )

        if root_name == "DatenBereitAnfrage":
            return ParsedInboundMessage(
                InboundMessageType.DATA_READY,
                service=service,
                producer_ref=producer_ref,
                message_name=root_name,
            )

        if root_name == "ClientStatusAnfrage":
            return ParsedInboundMessage(
                InboundMessageType.CLIENT_STATUS,
                service=service,
                producer_ref=producer_ref,
                service_started_time=first_datetime(root, "StartDienstZst"),
                message_name=root_name,
                include_active_subscriptions=(
                    (root.get("MitAbos") or "false").strip().lower() in {"true", "1"}
                ),
            )

        raise ValueError(f"Unsupported VDV inbound message type '{root_name}'")

    def build_inbound_response(
        self,
        message: ParsedInboundMessage,
        subscriptions: Sequence[SubscriptionRecord] = (),
    ) -> bytes:
        if message.message_type is InboundMessageType.DATA_READY:
            root = etree.Element("DatenBereitAntwort")
            etree.SubElement(
                root,
                "Bestaetigung",
                Zst=self._timestamp(),
                Ergebnis="ok",
                Fehlernummer="0",
            )
            return self._xml_bytes(root)

        if message.message_type is InboundMessageType.CLIENT_STATUS:
            root = etree.Element("ClientStatusAntwort")
            etree.SubElement(root, "Status", Zst=self._timestamp(), Ergebnis="ok")
            etree.SubElement(root, "StartDienstZst").text = self._service_started_at

            active = [
                record
                for record in subscriptions
                if record.status in {SubscriptionStatus.ACTIVE, SubscriptionStatus.DEGRADED}
            ]
            if message.include_active_subscriptions:
                active_element = etree.SubElement(root, "AktiveAbos")
                for record in active:
                    service_element = SERVICE_ELEMENTS.get(
                        self._service_key(record.config.service)
                    )
                    if service_element is None:
                        continue
                    active_subscription = etree.SubElement(
                        active_element,
                        service_element,
                        AboID=record.config.subscription_ref,
                        VerfallZst=record.config.initial_termination_time.isoformat()
                        if record.config.initial_termination_time is not None
                        else self._timestamp(),
                    )
                    self._build_service_subscription(
                        active_subscription, record.config
                    )

            return self._xml_bytes(root)

        raise ValueError(f"Unsupported VDV inbound message type {message.message_type}")

    def _build_service_subscription(
        self, request: etree._Element, config: SubscriptionCreate
    ) -> None:
        service = self._service_key(config.service)

        if service in {"CT", "CM"}:
            etree.SubElement(request, "ASBID").text = self._parameter(
                config, "asbId", required=True
            )
            return

        if service in {"ST", "SM"}:
            etree.SubElement(request, "AZBID").text = self._parameter(
                config, "azbId", required=True
            )
            return

        if service == "VM":
            etree.SubElement(request, "VISID").text = self._parameter(
                config, "visId", required=True
            )
            return

        if service in {"ET", "PT"}:
            for line in config.filters.lines:
                line_filter = etree.SubElement(request, "LinienFilter")
                etree.SubElement(line_filter, "LinienID").text = line
            for operator in config.filters.operators:
                operator_filter = etree.SubElement(request, "BetreiberFilter")
                etree.SubElement(operator_filter, "BetreiberID").text = operator
            return

    @staticmethod
    def _parameter(
        config: SubscriptionCreate, name: str, *, required: bool = False
    ) -> str | None:
        value = config.parameters.get(name)
        if value is None:
            if required:
                raise ValueError(
                    f"Profile 'de-vdv' version '2' service '{config.service}' requires "
                    f"parameters.{name}"
                )
            return None

        if isinstance(value, (dict, list)):
            raise ValueError(
                f"Profile 'de-vdv' version '2' parameter '{name}' must be a scalar value"
            )

        text = str(value).strip()
        if not text:
            raise ValueError(
                f"Profile 'de-vdv' version '2' parameter '{name}' must not be empty"
            )
        return text

    @staticmethod
    def _raise_on_negative_confirmation(root: etree._Element) -> None:
        confirmations = root.xpath(
            "//*[local-name()='Bestaetigung' or local-name()='BestaetigungMitAboID']"
        )
        for confirmation in confirmations:
            result = confirmation.get("Ergebnis")
            if result is None or result.strip().lower() == "ok":
                continue

            error_number = confirmation.get("Fehlernummer")
            error_text = first_text(confirmation, "FehlerText") or first_text(
                confirmation, "Fehlertext"
            )
            details = ": ".join(value for value in (error_number, error_text) if value)
            raise RuntimeError(
                f"VDV publisher rejected request{': ' + details if details else ''}"
            )

    @staticmethod
    def _service_key(service: str) -> str:
        return service.strip().upper().replace("_", "-")

    @staticmethod
    def _route_from_path(path: str | None) -> tuple[str | None, str | None]:
        if not path:
            return None, None

        parts = [part for part in path.split("/") if part]
        if len(parts) < 3:
            raise ValueError(
                "VDV inbound path must be <producer_ref>/<service>/<action>.xml"
            )

        producer_ref = parts[0]
        vdv_service = parts[1].strip().upper().replace("_", "-")
        try:
            service = SIRI_SERVICE_NAMES[vdv_service]
        except KeyError as exc:
            raise ValueError(f"Unsupported VDV service path '{parts[1]}'") from exc

        return producer_ref, service

    @staticmethod
    def _action_from_path(path: str | None) -> str | None:
        if not path:
            return None
        parts = [part for part in path.split("/") if part]
        return parts[2].strip().lower() if len(parts) >= 3 else None

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _xml_bytes(root: etree._Element) -> bytes:
        return etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=False,
        )
