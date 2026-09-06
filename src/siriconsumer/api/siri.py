from __future__ import annotations

from datetime import datetime

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from lxml import etree

from siriconsumer.api.dependencies import AppServices
from siriconsumer.infrastructure.xml_codec import first_datetime, first_text, local_name, parse_xml
from siriconsumer.siri_debug import log_siri_payload

logger = logging.getLogger(__name__)

router = APIRouter(tags=["siri"])


def _services(request: Request) -> AppServices:
    return request.app.state.services


def _ack(name: str) -> bytes:
    root = etree.Element("Siri")
    response = etree.SubElement(root, name)
    etree.SubElement(response, "Status").text = "true"

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


@router.post("/siri")
async def receive_siri(request: Request) -> Response:
    payload = await request.body()
    log_siri_payload(
        logger,
        enabled=request.app.state.settings.debug_siri_logging,
        direction="INCOMING REQUEST",
        payload=payload,
        endpoint=str(request.url),
    )

    try:
        root = parse_xml(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid XML: {exc}") from exc

    root_name = local_name(root)
    child_names = [local_name(child) for child in root.iter()]
    subscription_ref = first_text(root, "SubscriptionRef") or first_text(root, "SubscriptionIdentifier")

    if "DataReadyNotification" in child_names:
        if not subscription_ref:
            raise HTTPException(status_code=400, detail="Missing SubscriptionRef")

        await _services(request).fetched_delivery_service.schedule(subscription_ref)

        return Response(content=_ack("DataReadyAcknowledgement"), media_type="application/xml")

    if "HeartbeatNotification" in child_names or root_name == "HeartbeatNotification":
        service_started_time: datetime | None = first_datetime(root, "ServiceStartedTime")

        await _services(request).provider_monitor.record_heartbeat(subscription_ref, service_started_time)

        return Response(content=_ack("HeartbeatResponse"), media_type="application/xml")

    if "ServiceDelivery" in child_names or root_name == "ServiceDelivery":
        if not subscription_ref:
            raise HTTPException(status_code=400, detail="Missing SubscriptionRef")

        subscription = await _services(request).repository.get_by_ref(subscription_ref)
        if subscription is None:
            raise HTTPException(status_code=404, detail="Unknown subscription")

        await _services(request).delivery_service.accept(
            subscription.id,
            payload,
            request.headers.get("content-type"),
            "ServiceDelivery",
        )

        return Response(content=_ack("ServiceDeliveryResponse"), media_type="application/xml")

    raise HTTPException(status_code=400, detail="Unsupported SIRI message type")
