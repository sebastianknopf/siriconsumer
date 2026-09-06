from __future__ import annotations

from siriconsumer.infrastructure.xml_codec import first_text, parse_xml


def test_xml_parser_reads_namespaced_subscription_ref() -> None:
    root = parse_xml(
        b'<Siri xmlns="http://www.siri.org.uk/siri"><ServiceDelivery><SubscriptionRef>x</SubscriptionRef></ServiceDelivery></Siri>'
    )
    assert first_text(root, "SubscriptionRef") == "x"
