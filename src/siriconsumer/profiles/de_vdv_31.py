from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

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

VDV_453_VERSION = "3.1.0"
VDV_454_VERSION = "3.1.0"
VDV_XSD_VERSION = "VDV453_incl_454_V3.1.0_v12"

SERVICE_ELEMENTS = {
    "CT": "AboASBRef",
    "CM": "AboASB",
    "ST": "AboAZBRef",
    "SM": "AboAZB",
    "VM": "AboVIS",
    "PT": "AboAUSRef",
    "ET": "AboAUS",
}
VDV_SERVICE_NAMES = {
    "CT": "REF-ANS",
    "CM": "ANS",
    "ST": "REF-DFI",
    "SM": "DFI",
    "VM": "VIS",
    "PT": "REF-AUS",
    "ET": "AUS",
}
SIRI_SERVICE_NAMES = {vdv: siri for siri, vdv in VDV_SERVICE_NAMES.items()}
ACTION_PATHS = {
    PublisherAction.SUBSCRIBE: "aboverwalten.xml",
    PublisherAction.TERMINATE: "aboverwalten.xml",
    PublisherAction.CHECK_STATUS: "status.xml",
    PublisherAction.FETCH_DELIVERY: "datenabrufen.xml",
}


class GermanVdv31Profile(CommunicationProfile):
    profile_id = "de-vdv"
    version = "3.1"
    specification = "VDV 453 3.1.0 / VDV 454 3.1.0 using VDV453_incl_454_V3.1.0_v12"
    supported_services = ("CT", "CM", "ST", "SM", "VM", "PT", "ET")
    supported_parameters = {
        "CT": ("asbId", "earliestArrivalTime", "latestArrivalTime"),
        "CM": ("asbId", "journeyFilters", "timeFilter", "hysteresis"),
        "ST": ("azbId", "earliestDepartureTime", "latestDepartureTime"),
        "SM": ("azbId", "previewTime", "maxJourneys", "hysteresis", "maxTextLength", "onlyUpdates"),
        "VM": ("visId",),
        "PT": ("validFrom", "validUntil", "includeGuaranteedConnections", "includeAdditionalTimeWindows", "includeFormation"),
        "ET": ("hysteresis", "previewTime", "includeGuaranteedConnections", "includeRealTimes", "includeFormation", "onlyUpdates"),
    }
    fetched_delivery_message_name = "DatenAbrufenAntwort"

    def __init__(self) -> None:
        self._service_started_at = self._timestamp()

    def validate_subscription(self, config: SubscriptionCreate) -> None:
        if config.delivery_mode is not DeliveryMode.FETCHED:
            raise ValueError("Profile 'de-vdv' version '3.1' supports fetched delivery only")
        service = self._service_key(config.service)
        if service not in SERVICE_ELEMENTS:
            raise ValueError("Profile 'de-vdv' version '3.1' supports SIRI service codes CT, CM, ST, SM, VM, PT, and ET")
        if not config.producer_ref or not config.producer_ref.strip():
            raise ValueError("Profile 'de-vdv' version '3.1' requires producer_ref as the producer control-centre identifier")
        if config.initial_termination_time is None:
            raise ValueError("Profile 'de-vdv' version '3.1' requires initial_termination_time as VDV VerfallZst")

        required = {
            "CT": ("asbId", "earliestArrivalTime", "latestArrivalTime"),
            "ST": ("azbId", "earliestDepartureTime", "latestDepartureTime"),
            "SM": ("azbId", "previewTime", "hysteresis"),
            "VM": ("visId",),
            "PT": ("validFrom", "validUntil"),
            "ET": ("hysteresis", "previewTime"),
        }.get(service, ())
        for name in required:
            self._parameter(config, name, required=True)

        if service == "CM":
            self._parameter(config, "asbId", required=True)
            self._parameter(config, "hysteresis", required=True)
            journeys = config.parameters.get("journeyFilters")
            time_filter = config.parameters.get("timeFilter")
            if bool(journeys) == bool(time_filter):
                raise ValueError("Profile 'de-vdv' version '3.1' service 'CM' requires either parameters.journeyFilters or parameters.timeFilter, but not both")
            if journeys is not None and not isinstance(journeys, list):
                raise ValueError("parameters.journeyFilters must be a list")
            if time_filter is not None and not isinstance(time_filter, dict):
                raise ValueError("parameters.timeFilter must be an object")

        if config.filters.directions and not config.filters.lines:
            raise ValueError("filters.directions requires at least one filters.lines entry")
        if service in {"CT", "CM", "VM"}:
            if len(config.filters.lines) > 1 or len(config.filters.directions) > 1:
                raise ValueError(
                    f"Profile 'de-vdv' version '3.1' service '{service}' supports at most "
                    "one filters.lines and one filters.directions entry"
                )
        if service in {"PT", "ET"}:
            self._validate_stop_filters(config)

    def resolve_endpoint(self, action: PublisherAction, subscription: SubscriptionRecord) -> str:
        return f"{str(subscription.config.provider_url).rstrip('/')}/{ACTION_PATHS[action]}"

    def build_subscription_request(self, subscription: SubscriptionRecord) -> bytes:
        config = subscription.config
        root = etree.Element("AboAnfrage", Sender=config.requestor_ref, Zst=self._timestamp(), XSDVersionID=VDV_XSD_VERSION)
        request = etree.SubElement(
            root,
            SERVICE_ELEMENTS[self._service_key(config.service)],
            AboID=config.subscription_ref,
            VerfallZst=config.initial_termination_time.isoformat() if config.initial_termination_time else "",
        )
        self._build_service_subscription(request, config)
        return self._xml_bytes(root)

    def build_termination_request(self, subscription: SubscriptionRecord) -> bytes:
        root = etree.Element("AboAnfrage", Sender=subscription.config.requestor_ref, Zst=self._timestamp(), XSDVersionID=VDV_XSD_VERSION)
        etree.SubElement(root, "AboLoeschen").text = subscription.config.subscription_ref
        return self._xml_bytes(root)

    def build_check_status_request(self, subscription: SubscriptionRecord) -> bytes:
        return self._xml_bytes(etree.Element("StatusAnfrage", Sender=subscription.config.requestor_ref, Zst=self._timestamp()))

    def build_data_supply_request(self, subscription: SubscriptionRecord) -> bytes:
        root = etree.Element("DatenAbrufenAnfrage", Sender=subscription.config.requestor_ref, Zst=self._timestamp())
        etree.SubElement(root, "DatensatzAlle").text = "false"
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
        nodes = root.xpath("//*[local-name()='Status']")
        result = nodes[0].get("Ergebnis") if nodes else None
        return ProviderStatus(
            healthy=result is not None and result.strip().lower() == "ok",
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
        expected = {"DatenBereitAnfrage": "datenbereit.xml", "ClientStatusAnfrage": "clientstatus.xml"}.get(root_name)
        if expected is not None and action != expected:
            raise ValueError(f"VDV message '{root_name}' must use action path '{expected}'")
        if root_name == "DatenBereitAnfrage":
            return ParsedInboundMessage(InboundMessageType.DATA_READY, service=service, producer_ref=producer_ref, message_name=root_name)
        if root_name == "ClientStatusAnfrage":
            return ParsedInboundMessage(
                InboundMessageType.CLIENT_STATUS,
                service=service,
                producer_ref=producer_ref,
                service_started_time=first_datetime(root, "StartDienstZst"),
                message_name=root_name,
                include_active_subscriptions=(root.get("MitAbos") or "false").strip().lower() in {"true", "1"},
            )
        raise ValueError(f"Unsupported VDV inbound message type '{root_name}'")

    def build_inbound_response(self, message: ParsedInboundMessage, subscriptions: Sequence[SubscriptionRecord] = ()) -> bytes:
        if message.message_type is InboundMessageType.DATA_READY:
            root = etree.Element("DatenBereitAntwort")
            etree.SubElement(root, "Bestaetigung", Zst=self._timestamp(), Ergebnis="ok", Fehlernummer="0")
            return self._xml_bytes(root)
        if message.message_type is InboundMessageType.CLIENT_STATUS:
            root = etree.Element("ClientStatusAntwort")
            etree.SubElement(root, "Status", Zst=self._timestamp(), Ergebnis="ok")
            etree.SubElement(root, "StartDienstZst").text = self._service_started_at
            if message.include_active_subscriptions:
                active_element = etree.SubElement(root, "AktiveAbos")
                for record in subscriptions:
                    if record.status not in {SubscriptionStatus.ACTIVE, SubscriptionStatus.DEGRADED}:
                        continue
                    element = SERVICE_ELEMENTS.get(self._service_key(record.config.service))
                    if element is None:
                        continue
                    child = etree.SubElement(active_element, element, AboID=record.config.subscription_ref, VerfallZst=record.config.initial_termination_time.isoformat() if record.config.initial_termination_time else self._timestamp())
                    self._build_service_subscription(child, record.config)
            return self._xml_bytes(root)
        raise ValueError(f"Unsupported VDV inbound message type {message.message_type}")

    def _build_service_subscription(self, request: etree._Element, config: SubscriptionCreate) -> None:
        service = self._service_key(config.service)
        if service == "CT":
            self._text(request, "ASBID", self._parameter(config, "asbId", required=True))
            self._optional_text(request, "LinienID", self._single_filter(config.filters.lines))
            self._optional_text(request, "RichtungsID", self._single_filter(config.filters.directions))
            self._text(request, "FruehesteAnkunftszeit", self._parameter(config, "earliestArrivalTime", required=True))
            self._text(request, "SpaetesteAnkunftszeit", self._parameter(config, "latestArrivalTime", required=True))
        elif service == "CM":
            self._build_cm(request, config)
        elif service == "ST":
            self._text(request, "AZBID", self._parameter(config, "azbId", required=True))
            self._build_line_filters(request, config)
            self._text(request, "FruehesteAbfahrtszeit", self._parameter(config, "earliestDepartureTime", required=True))
            self._text(request, "SpaetesteAbfahrtszeit", self._parameter(config, "latestDepartureTime", required=True))
        elif service == "SM":
            self._text(request, "AZBID", self._parameter(config, "azbId", required=True))
            self._build_line_filters(request, config)
            self._text(request, "Vorschauzeit", self._parameter(config, "previewTime", required=True))
            self._optional_text(request, "MaxAnzahlFahrten", self._parameter(config, "maxJourneys"))
            self._text(request, "Hysterese", self._parameter(config, "hysteresis", required=True))
            self._optional_text(request, "MaxTextLaenge", self._parameter(config, "maxTextLength"))
            self._optional_bool(request, "NurAktualisierung", config.parameters.get("onlyUpdates"))
        elif service == "VM":
            self._text(request, "VISID", self._parameter(config, "visId", required=True))
            self._optional_text(request, "LinienID", self._single_filter(config.filters.lines))
            self._optional_text(request, "RichtungsID", self._single_filter(config.filters.directions))
        elif service == "PT":
            window = etree.SubElement(request, "Zeitfenster")
            self._text(window, "GueltigVon", self._parameter(config, "validFrom", required=True))
            self._text(window, "GueltigBis", self._parameter(config, "validUntil", required=True))
            self._build_aus_filters(request, config)
            self._optional_bool(request, "MitGesAnschluss", config.parameters.get("includeGuaranteedConnections"))
            self._optional_bool(request, "MitZusaetzlichenZeitfenstern", config.parameters.get("includeAdditionalTimeWindows"))
            self._optional_bool(request, "MitFormation", config.parameters.get("includeFormation"))
        elif service == "ET":
            self._build_aus_filters(request, config)
            self._text(request, "Hysterese", self._parameter(config, "hysteresis", required=True))
            self._text(request, "Vorschauzeit", self._parameter(config, "previewTime", required=True))
            self._optional_bool(request, "MitGesAnschluss", config.parameters.get("includeGuaranteedConnections"))
            self._optional_bool(request, "MitRealZeiten", config.parameters.get("includeRealTimes"))
            self._optional_bool(request, "MitFormation", config.parameters.get("includeFormation"))
            self._optional_bool(request, "NurAktualisierung", config.parameters.get("onlyUpdates"))

    def _build_cm(self, request: etree._Element, config: SubscriptionCreate) -> None:
        self._text(request, "ASBID", self._parameter(config, "asbId", required=True))
        journeys = config.parameters.get("journeyFilters") or []
        for item in journeys:
            if not isinstance(item, dict):
                raise ValueError("Each parameters.journeyFilters item must be an object")
            node = etree.SubElement(request, "FahrtFilter")
            journey_id = etree.SubElement(node, "FahrtID")
            self._text(journey_id, "FahrtBezeichner", self._dict_value(item, "journeyRef"))
            self._text(journey_id, "Betriebstag", self._dict_value(item, "operatingDay"))
            self._text(node, "HstSeqZaehler", self._dict_value(item, "stopSequenceCounter"))
            self._text(node, "AnkunftszeitASBPlan", self._dict_value(item, "plannedArrivalTime"))
            self._text(node, "Vorschauzeit", self._dict_value(item, "previewTime"))
        time_filter = config.parameters.get("timeFilter")
        if isinstance(time_filter, dict):
            node = etree.SubElement(request, "ZeitFilter")
            self._optional_text(node, "LinienID", self._single_filter(config.filters.lines))
            self._optional_text(node, "RichtungsID", self._single_filter(config.filters.directions))
            self._text(node, "FruehesteAnkunftszeit", self._dict_value(time_filter, "earliestArrivalTime"))
            self._text(node, "SpaetesteAnkunftszeit", self._dict_value(time_filter, "latestArrivalTime"))
            self._optional_text(node, "Vorschauzeit", self._dict_optional(time_filter, "previewTime"))
        self._text(request, "Hysterese", self._parameter(config, "hysteresis", required=True))

    def _build_line_filters(self, request: etree._Element, config: SubscriptionCreate) -> None:
        for line, direction in self._line_filter_pairs(config):
            node = etree.SubElement(request, "LinienFilter")
            self._text(node, "LinienID", line)
            self._optional_text(node, "RichtungsID", direction)

    def _build_aus_filters(self, request: etree._Element, config: SubscriptionCreate) -> None:
        self._build_line_filters(request, config)
        for operator in config.filters.operators:
            node = etree.SubElement(request, "BetreiberFilter")
            self._text(node, "BetreiberID", operator)
        for product in config.filters.products:
            node = etree.SubElement(request, "ProduktFilter")
            self._text(node, "ProduktID", product)
        for vehicle_mode in config.filters.vehicle_modes:
            node = etree.SubElement(request, "VerkehrsmittelIDFilter")
            self._text(node, "VerkehrsmittelID", vehicle_mode)
        for stop_group in config.filters.stops:
            node = etree.SubElement(request, "HaltFilter")
            for stop in stop_group:
                halt = etree.SubElement(node, "HaltID")
                self._optional_text(halt, "HaltestellenID", stop.stop_id)
                self._optional_text(halt, "BereichsID", stop.area_id)
                self._optional_text(halt, "SteigID", stop.platform_id)
                self._optional_text(halt, "SektorenID", stop.sector_id)

    @staticmethod
    def _line_filter_pairs(config: SubscriptionCreate) -> list[tuple[str, str | None]]:
        if not config.filters.directions:
            return [(line, None) for line in config.filters.lines]
        return [
            (line, direction)
            for line in config.filters.lines
            for direction in config.filters.directions
        ]

    @staticmethod
    def _single_filter(values: list[str]) -> str | None:
        return values[0] if values else None

    @staticmethod
    def _validate_stop_filters(config: SubscriptionCreate) -> None:
        for group in config.filters.stops:
            if not group:
                raise ValueError("Each filters.stops group must contain at least one stop")
            for stop in group:
                if not any((stop.stop_id, stop.area_id, stop.platform_id, stop.sector_id)):
                    raise ValueError("Each filters.stops[][] entry must contain at least one stop identifier")

    @staticmethod
    def _parameter(config: SubscriptionCreate, name: str, *, required: bool = False) -> str | None:
        value = config.parameters.get(name)
        if value is None:
            if required:
                raise ValueError(f"Profile 'de-vdv' version '3.1' service '{config.service}' requires parameters.{name}")
            return None
        if isinstance(value, (dict, list, bool)):
            raise ValueError(f"Profile 'de-vdv' version '3.1' parameter '{name}' must be a scalar value")
        text = str(value).strip()
        if not text:
            raise ValueError(f"Profile 'de-vdv' version '3.1' parameter '{name}' must not be empty")
        return text

    @staticmethod
    def _dict_value(item: dict[str, Any], name: str) -> str:
        value = item.get(name)
        if value is None or isinstance(value, (dict, list, bool)) or not str(value).strip():
            raise ValueError(f"parameters.journeyFilters/timeFilter field '{name}' is required and must be scalar")
        return str(value).strip()

    @staticmethod
    def _dict_optional(item: dict[str, Any], name: str) -> str | None:
        value = item.get(name)
        return None if value is None else str(value).strip() or None

    @staticmethod
    def _text(parent: etree._Element, name: str, value: str | None) -> None:
        if value is None:
            raise ValueError(f"Missing required VDV element {name}")
        etree.SubElement(parent, name).text = value

    @staticmethod
    def _optional_text(parent: etree._Element, name: str, value: str | None) -> None:
        if value is not None:
            etree.SubElement(parent, name).text = value

    @staticmethod
    def _optional_bool(parent: etree._Element, name: str, value: Any) -> None:
        if value is None:
            return
        if not isinstance(value, bool):
            raise ValueError(f"parameters value for {name} must be boolean")
        etree.SubElement(parent, name).text = "true" if value else "false"

    @staticmethod
    def _raise_on_negative_confirmation(root: etree._Element) -> None:
        confirmations = root.xpath("//*[local-name()='Bestaetigung' or local-name()='BestaetigungMitAboID']")
        for confirmation in confirmations:
            result = confirmation.get("Ergebnis")
            if result is None or result.strip().lower() == "ok":
                continue
            number = confirmation.get("Fehlernummer")
            error_text = first_text(confirmation, "FehlerText") or first_text(confirmation, "Fehlertext")
            details = ": ".join(value for value in (number, error_text) if value)
            raise RuntimeError(f"VDV publisher rejected request{': ' + details if details else ''}")

    @staticmethod
    def _service_key(service: str) -> str:
        return service.strip().upper().replace("_", "-")

    @staticmethod
    def _route_from_path(path: str | None) -> tuple[str | None, str | None]:
        if not path:
            return None, None
        parts = [part for part in path.split("/") if part]
        if len(parts) < 3:
            raise ValueError("VDV inbound path must be <producer_ref>/<service>/<action>.xml")
        producer_ref = parts[0]
        try:
            service = SIRI_SERVICE_NAMES[parts[1].strip().upper().replace("_", "-")]
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
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
