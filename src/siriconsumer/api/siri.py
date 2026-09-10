from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response
from lxml import etree

from siriconsumer.api.dependencies import AppServices
from siriconsumer.infrastructure.xml_codec import first_datetime, first_text, local_name, parse_xml
from siriconsumer.interfaces.intf_delivery_admission import (
    DeliveryAdmissionClosedError,
    DeliveryAdmissionDeletedError,
)
from siriconsumer.interfaces.intf_spool import SpoolCapacityTimeoutError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["siri"])


def _services(request: Request) -> AppServices:
    return request.app.state.services


def _ack(name: str) -> bytes:
    root = etree.Element("Siri")
    response = etree.SubElement(root, name)
    etree.SubElement(response, "Status").text = "true"

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _xml_response(request: Request, payload: bytes) -> Response:
    _services(request).communication_monitor.publish(
        direction="outgoing",
        kind="response",
        payload=payload,
        endpoint=str(request.url),
        status_code=200,
    )
    
    return Response(content=payload, media_type="application/xml")


@router.post("/siri")
async def receive_siri(request: Request) -> Response:
    payload = await request.body()
    _services(request).communication_monitor.publish(
        direction="incoming",
        kind="request",
        payload=payload,
        endpoint=str(request.url),
    )

    try:
        root = parse_xml(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid XML: {exc}") from exc

    root_name = local_name(root)
    child_names = [local_name(child) for child in root.iter()]
    subscription_ref = first_text(root, "SubscriptionRef") or first_text(
        root, "SubscriptionIdentifier"
    )

    if "DataReadyNotification" in child_names:
        if not subscription_ref:
            raise HTTPException(status_code=400, detail="Missing SubscriptionRef")

        await _services(request).fetched_delivery_service.schedule(subscription_ref)

        return _xml_response(request, _ack("DataReadyAcknowledgement"))

    if "HeartbeatNotification" in child_names or root_name == "HeartbeatNotification":
        service_started_time: datetime | None = first_datetime(root, "ServiceStartedTime")

        await _services(request).provider_monitor.record_heartbeat(
            subscription_ref, service_started_time
        )

        return _xml_response(request, _ack("HeartbeatResponse"))

    if "ServiceDelivery" in child_names or root_name == "ServiceDelivery":
        if not subscription_ref:
            raise HTTPException(status_code=400, detail="Missing SubscriptionRef")

        try:
            await _services(request).delivery_service.accept(
                subscription_ref,
                payload,
                request.headers.get("content-type"),
                "ServiceDelivery",
                wait_timeout_seconds=(
                    request.app.state.settings.direct_delivery_throttle_timeout_seconds
                ),
            )
        except DeliveryAdmissionClosedError as exc:
            raise HTTPException(
                status_code=410,
                detail="Subscription is terminating or has been deleted",
            ) from exc
        except (DeliveryAdmissionDeletedError, KeyError) as exc:
            raise HTTPException(status_code=404, detail="Unknown subscription") from exc
        except SpoolCapacityTimeoutError as exc:
            logger.warning(
                "Direct delivery rejected with HTTP 503 after spool throttle timeout "
                "subscription_ref=%s timeout_seconds=%s",
                subscription_ref,
                request.app.state.settings.direct_delivery_throttle_timeout_seconds,
            )
            raise HTTPException(
                status_code=503,
                detail="Spool capacity is currently exhausted; retry delivery later",
            ) from exc

        return _xml_response(request, _ack("ServiceDeliveryResponse"))

    raise HTTPException(status_code=400, detail="Unsupported SIRI message type")
