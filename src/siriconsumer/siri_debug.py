from __future__ import annotations

import logging

from lxml import etree


def pretty_xml(payload: bytes) -> str:
    """Return an XML payload formatted for debug logging without changing the payload."""
    try:
        parser = etree.XMLParser(remove_blank_text=True, resolve_entities=False, no_network=True)
        root = etree.fromstring(payload, parser=parser)

        return etree.tostring(root, encoding="unicode", pretty_print=True).rstrip()
    except (etree.XMLSyntaxError, ValueError):
        return payload.decode("utf-8", errors="replace")


def log_siri_payload(
    logger: logging.Logger,
    *,
    enabled: bool,
    direction: str,
    payload: bytes,
    endpoint: str | None = None,
) -> None:
    if not enabled:
        return

    location = f" endpoint={endpoint}" if endpoint else ""
    logger.debug("SIRI %s%s\n%s", direction, location, pretty_xml(payload))
