from __future__ import annotations

import logging

from siriconsumer.siri_debug import log_siri_payload, pretty_xml


def test_pretty_xml_formats_siri_payload() -> None:
    result = pretty_xml(b"<Siri><CheckStatusRequest><Status>true</Status></CheckStatusRequest></Siri>")
    assert "\n" in result
    assert "  <CheckStatusRequest>" in result


def test_debug_logging_can_be_disabled(caplog) -> None:
    logger = logging.getLogger("test.siri.debug")
    with caplog.at_level(logging.DEBUG):
        log_siri_payload(logger, enabled=False, direction="INCOMING REQUEST", payload=b"<Siri/>")
    assert "SIRI INCOMING REQUEST" not in caplog.text


def test_debug_logging_pretty_prints_payload(caplog) -> None:
    logger = logging.getLogger("test.siri.debug")
    with caplog.at_level(logging.DEBUG):
        log_siri_payload(
            logger,
            enabled=True,
            direction="OUTGOING REQUEST",
            payload=b"<Siri><Status>true</Status></Siri>",
        )
    assert "SIRI OUTGOING REQUEST" in caplog.text
    assert "  <Status>true</Status>" in caplog.text
