from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from lxml import etree

from siriconsumer.domain.models import SubscriptionRecord
from siriconsumer.interfaces.intf_communication_logger import (
    CommunicationDirection,
    CommunicationKind,
)

logger = logging.getLogger(__name__)

COMMUNICATION_LOG_ROOT = Path("/var/log/siri")


class FileCommunicationLogger:
    """Persist per-subscription XML communication without lifecycle cleanup."""

    async def write(
        self,
        subscription: SubscriptionRecord,
        *,
        direction: CommunicationDirection,
        kind: CommunicationKind,
        payload: bytes,
    ) -> None:
        if not subscription.config.logging:
            return

        try:
            await asyncio.to_thread(
                self._write_pretty_xml,
                subscription.config.subscription_ref,
                direction,
                kind,
                payload,
            )
        except Exception:
            logger.exception(
                "Failed to persist communication XML subscription_ref=%s direction=%s kind=%s",
                subscription.config.subscription_ref,
                direction,
                kind,
            )

    def _write_pretty_xml(
        self,
        subscription_ref: str,
        direction: CommunicationDirection,
        kind: CommunicationKind,
        payload: bytes,
    ) -> None:
        parser = etree.XMLParser(remove_blank_text=True, resolve_entities=False, no_network=True)
        root = etree.fromstring(payload, parser=parser)
        pretty_payload = etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=True,
        )

        directory = COMMUNICATION_LOG_ROOT / quote(subscription_ref, safe="")
        directory.mkdir(parents=True, exist_ok=True)

        while True:
            now = datetime.now().astimezone()
            timestamp = now.strftime("%Y-%m-%d-%H-%M-%S-") + f"{now.microsecond // 1000:03d}"
            path = directory / f"{timestamp}_{direction}_{kind}.xml"
            try:
                with path.open("xb") as stream:
                    stream.write(pretty_payload)
                return
            except FileExistsError:
                continue
