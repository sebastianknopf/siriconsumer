from __future__ import annotations

from datetime import datetime

from lxml import etree

SIRI_NS = "http://www.siri.org.uk/siri"
NSMAP = {None: SIRI_NS}


def parse_xml(payload: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    return etree.fromstring(payload, parser=parser)


def local_name(element: etree._Element) -> str:
    return etree.QName(element.tag).localname


def first_text(root: etree._Element, name: str) -> str | None:
    matches = root.xpath(f"//*[local-name()='{name}']/text()")
    return str(matches[0]) if matches else None


def first_datetime(root: etree._Element, name: str) -> datetime | None:
    value = first_text(root, name)
    if not value:
        return None
    
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def xml_bytes(element: etree._Element) -> bytes:
    return etree.tostring(element, xml_declaration=True, encoding="UTF-8")
