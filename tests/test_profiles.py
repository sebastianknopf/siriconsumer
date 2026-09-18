from __future__ import annotations

from datetime import datetime, timezone

import pytest
from lxml import etree

from siriconsumer.domain.models import SubscriptionCreate, SubscriptionRecord
from siriconsumer.interfaces.intf_profile import InboundMessageType, PublisherAction
from siriconsumer.profiles.de_vdv_2 import GermanVdv2Profile
from siriconsumer.profiles.registry import ProfileRegistry, UnknownProfileError


def _vdv_config(service: str = "ET") -> SubscriptionCreate:
    return SubscriptionCreate.model_validate(
        {
            "provider_url": "https://publisher.example/vdv/aus",
            "profile": "de-vdv",
            "version": "2",
            "service": service,
            "delivery_mode": "fetched",
            "requestor_ref": "consumer-control-centre",
            "subscriber_ref": "consumer",
            "producer_ref": "producer-control-centre",
            "subscription_ref": "abo-17",
            "initial_termination_time": "2026-09-19T04:00:00Z",
            "parameters": {
                "asbId": "ASB-123",
                "azbId": "AZB-456",
                "visId": "VIS-789",
            },
            "filters": {
                "lines": ["10"],
                "operators": ["85:11"],
            },
            "sink": {"type": "directory", "path": "/tmp/vdv"},
        }
    )


def test_subscription_profile_defaults_to_default() -> None:
    config = SubscriptionCreate.model_validate(
        {
            "provider_url": "https://publisher.example/siri",
            "service": "VM",
            "delivery_mode": "direct",
            "requestor_ref": "consumer",
            "subscriber_ref": "consumer",
            "producer_ref": "producer-control-centre",
            "subscription_ref": "sub-1",
            "sink": {"type": "directory", "path": "/tmp/siri"},
        }
    )

    assert config.profile == "default"
    assert config.version == "default"


def test_profile_registry_supports_versioned_vdv_profile() -> None:
    registry = ProfileRegistry()

    assert registry.get("default", "default").profile_id == "default"
    assert registry.get("de-vdv", "2").profile_id == "de-vdv"
    with pytest.raises(UnknownProfileError):
        registry.get("de-vdv", "3.1")


def test_vdv_profile_builds_action_specific_urls_and_subscription_xml() -> None:
    profile = GermanVdv2Profile()
    record = SubscriptionRecord(config=_vdv_config())

    assert profile.resolve_endpoint(PublisherAction.SUBSCRIBE, record) == (
        "https://publisher.example/vdv/aus/aboverwalten.xml"
    )
    assert profile.resolve_endpoint(PublisherAction.CHECK_STATUS, record) == (
        "https://publisher.example/vdv/aus/status.xml"
    )
    assert profile.resolve_endpoint(PublisherAction.FETCH_DELIVERY, record) == (
        "https://publisher.example/vdv/aus/datenabrufen.xml"
    )

    root = etree.fromstring(profile.build_subscription_request(record))
    assert root.tag == "AboAnfrage"
    assert root.get("Sender") == "consumer-control-centre"
    abo = root.find("AboAUS")
    assert abo is not None
    assert abo.get("AboID") == "abo-17"
    assert abo.findtext("LinienFilter/LinienID") == "10"
    assert abo.findtext("BetreiberFilter/BetreiberID") == "85:11"


def test_vdv_profile_requires_fetched_delivery_and_expiry() -> None:
    profile = GermanVdv2Profile()
    direct = _vdv_config().model_copy(update={"delivery_mode": "direct"})

    with pytest.raises(ValueError, match="fetched delivery only"):
        profile.validate_subscription(direct)

    no_expiry = _vdv_config().model_copy(update={"initial_termination_time": None})
    with pytest.raises(ValueError, match="initial_termination_time"):
        profile.validate_subscription(no_expiry)


def test_vdv_profile_parses_more_data_and_status() -> None:
    profile = GermanVdv2Profile()

    assert profile.has_more_data(
        b"<DatenAbrufenAntwort><WeitereDaten>true</WeitereDaten></DatenAbrufenAntwort>"
    )
    assert profile.has_more_data(
        b'<DatenAbrufenAntwort WeitereDaten="true"><Bestaetigung/></DatenAbrufenAntwort>'
    )
    assert not profile.has_more_data(b"<DatenAbrufenAntwort/>")

    status = profile.parse_provider_status(
        b"<StatusAntwort>"
        b'<Status Zst="2026-09-18T08:00:00Z" Ergebnis="ok"/>'
        b"<StartDienstZst>2026-09-18T07:00:00Z</StartDienstZst>"
        b"</StatusAntwort>"
    )
    assert status.healthy is True
    assert status.service_started_time == datetime(2026, 9, 18, 7, 0, tzinfo=timezone.utc)


def test_vdv_profile_parses_data_ready_from_profile_path() -> None:
    profile = GermanVdv2Profile()
    message = profile.parse_inbound(
        b'<DatenBereitAnfrage Sender="producer" Zst="2026-09-18T08:00:00Z"/>',
        "producer-control-centre/AUS/datenbereit.xml",
    )

    assert message.message_type is InboundMessageType.DATA_READY
    assert message.service == "ET"
    assert message.producer_ref == "producer-control-centre"
    response = profile.build_inbound_response(message)
    root = etree.fromstring(response)
    assert root.tag == "DatenBereitAntwort"
    assert root.find("Bestaetigung").get("Ergebnis") == "ok"  # type: ignore[union-attr]



@pytest.mark.parametrize(
    ("service", "element"),
    [
        ("CT", "AboASBRef"),
        ("CM", "AboASB"),
        ("ST", "AboAZBRef"),
        ("SM", "AboAZB"),
        ("VM", "AboVIS"),
        ("PT", "AboAUSRef"),
        ("ET", "AboAUS"),
    ],
)
def test_vdv_profile_uses_canonical_service_names(service: str, element: str) -> None:
    config = _vdv_config(service)
    profile = GermanVdv2Profile()
    profile.validate_subscription(config)

    root = etree.fromstring(
        profile.build_subscription_request(SubscriptionRecord(config=config))
    )

    abo = root.find(element)
    assert abo is not None
    assert abo.get("AboID") == "abo-17"


def test_vdv_profile_rejects_xml_structure_names_and_and_service() -> None:
    profile = GermanVdv2Profile()

    for service in ("ASB", "ASB-REF", "AZB", "AZB-REF", "AND"):
        with pytest.raises(ValueError, match="supports SIRI service codes"):
            profile.validate_subscription(_vdv_config(service))


def test_vdv_profile_uses_requestor_ref_as_sender() -> None:
    config = _vdv_config().model_copy(
        update={
            "requestor_ref": "vdv-consumer",
            "subscriber_ref": "subscriber-ref-is-not-vdv-sender",
        }
    )
    profile = GermanVdv2Profile()
    record = SubscriptionRecord(config=config)

    for payload in (
        profile.build_subscription_request(record),
        profile.build_termination_request(record),
        profile.build_check_status_request(record),
        profile.build_data_supply_request(record),
    ):
        root = etree.fromstring(payload)
        assert root.get("Sender") == "vdv-consumer"


@pytest.mark.parametrize(
    ("service", "parameter", "element", "value"),
    [
        ("CT", "asbId", "ASBID", "ASB-123"),
        ("CM", "asbId", "ASBID", "ASB-123"),
        ("ST", "azbId", "AZBID", "AZB-456"),
        ("SM", "azbId", "AZBID", "AZB-456"),
        ("VM", "visId", "VISID", "VIS-789"),
    ],
)
def test_vdv_profile_maps_profile_parameters(
    service: str, parameter: str, element: str, value: str
) -> None:
    config = _vdv_config(service)
    profile = GermanVdv2Profile()

    root = etree.fromstring(
        profile.build_subscription_request(SubscriptionRecord(config=config))
    )

    subscription = root.find({"CT": "AboASBRef", "CM": "AboASB", "ST": "AboAZBRef", "SM": "AboAZB", "VM": "AboVIS"}[service])
    assert subscription is not None
    assert subscription.findtext(element) == value

    missing = config.model_copy(
        update={
            "parameters": {
                key: item
                for key, item in config.parameters.items()
                if key != parameter
            }
        }
    )
    with pytest.raises(ValueError, match=f"parameters.{parameter}"):
        profile.validate_subscription(missing)


def test_profile_parameters_are_generic_subscription_data() -> None:
    config = _vdv_config().model_copy(
        update={"parameters": {"futureFlag": True, "futureNumber": 42}}
    )

    assert config.parameters == {"futureFlag": True, "futureNumber": 42}


def test_vdv_profile_requires_producer_ref() -> None:
    profile = GermanVdv2Profile()
    config = _vdv_config().model_copy(update={"producer_ref": None})

    with pytest.raises(ValueError, match="producer_ref"):
        profile.validate_subscription(config)


@pytest.mark.parametrize(
    ("siri_service", "vdv_service"),
    [
        ("CT", "REF-ANS"),
        ("CM", "ANS"),
        ("ST", "REF-DFI"),
        ("SM", "DFI"),
        ("VM", "VIS"),
        ("PT", "REF-AUS"),
        ("ET", "AUS"),
    ],
)
def test_vdv_inbound_path_maps_vdv_service_to_siri_service(
    siri_service: str, vdv_service: str
) -> None:
    profile = GermanVdv2Profile()
    message = profile.parse_inbound(
        b'<DatenBereitAnfrage Sender="producer-control-centre" Zst="2026-09-18T08:00:00Z"/>',
        f"producer-control-centre/{vdv_service}/datenbereit.xml",
    )

    assert message.service == siri_service
    assert message.producer_ref == "producer-control-centre"
