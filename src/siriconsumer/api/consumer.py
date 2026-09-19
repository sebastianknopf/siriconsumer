from __future__ import annotations

import logging
from collections.abc import Sequence

from fastapi import APIRouter, HTTPException, Request, Response

from siriconsumer.api.dependencies import AppServices
from siriconsumer.domain.models import SubscriptionRecord
from siriconsumer.interfaces.intf_communication_logger import (
    CommunicationDirection,
    CommunicationKind,
)
from siriconsumer.interfaces.intf_delivery_admission import (
    DeliveryAdmissionClosedError,
    DeliveryAdmissionDeletedError,
)
from siriconsumer.interfaces.intf_profile import InboundMessageType
from siriconsumer.interfaces.intf_spool import SpoolCapacityTimeoutError
from siriconsumer.profiles.registry import UnknownProfileError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["consumer"])


def _services(request: Request) -> AppServices:
    return request.app.state.services


async def _matching_profile_subscriptions(
    request: Request,
    profile_id: str,
    version: str,
    service: str,
    producer_ref: str | None,
):
    records = await _services(request).repository.list_by_profile_service(
        profile_id, version, service
    )
    if producer_ref is None:
        return records

    return [record for record in records if record.config.producer_ref == producer_ref]


async def _log_for_subscriptions(
    request: Request,
    subscriptions: Sequence[SubscriptionRecord],
    *,
    direction: CommunicationDirection,
    kind: CommunicationKind,
    payload: bytes,
) -> None:
    for subscription in subscriptions:
        await _services(request).communication_logger.write(
            subscription,
            direction=direction,
            kind=kind,
            payload=payload,
        )


async def _xml_response(
    request: Request, payload: bytes, subscriptions: Sequence[SubscriptionRecord]
) -> Response:
    await _log_for_subscriptions(
        request,
        subscriptions,
        direction="IN",
        kind="Response",
        payload=payload,
    )
    return Response(content=payload, media_type="application/xml")


@router.post("")
@router.post("/")
async def receive_default_consumer(request: Request) -> Response:
    return await _receive_profiled(request, "default", "default", None)


@router.post("/profile/{profile_id}/{version}")
async def receive_profile_root(profile_id: str, version: str, request: Request) -> Response:
    return await _receive_profiled(request, profile_id, version, None)


@router.post("/profile/{profile_id}/{version}/{path:path}")
async def receive_profiled_consumer(
    profile_id: str, version: str, path: str, request: Request
) -> Response:
    return await _receive_profiled(request, profile_id, version, path)


async def _receive_profiled(
    request: Request, profile_id: str, version: str, path: str | None
) -> Response:
    services = _services(request)
    try:
        profile = services.profile_registry.get(profile_id, version)
    except UnknownProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    payload = await request.body()

    try:
        message = profile.parse_inbound(payload, path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid or unsupported XML: {exc}") from exc

    subscriptions = []
    if message.subscription_ref:
        subscription = await services.repository.get(message.subscription_ref)
        if subscription is not None:
            subscriptions = [subscription]

    if message.message_type is InboundMessageType.DATA_READY and not message.subscription_ref:
        if not message.service:
            raise HTTPException(
                status_code=400,
                detail="Data-ready notification cannot be mapped to a subscription or service",
            )
        subscriptions = await _matching_profile_subscriptions(
            request, profile_id, version, message.service, message.producer_ref
        )
        if not subscriptions:
            raise HTTPException(
                status_code=404, detail="No subscription matches producer and service"
            )

    elif message.message_type is InboundMessageType.CLIENT_STATUS:
        if message.service:
            subscriptions = await _matching_profile_subscriptions(
                request, profile_id, version, message.service, message.producer_ref
            )
            if message.producer_ref is not None and not subscriptions:
                raise HTTPException(
                    status_code=404, detail="No subscription matches producer and service"
                )
        else:
            subscriptions = [
                record
                for record in await services.repository.list_all()
                if record.config.profile == profile_id and record.config.version == version
            ]

    await _log_for_subscriptions(
        request,
        subscriptions,
        direction="IN",
        kind="Request",
        payload=payload,
    )

    if message.message_type is InboundMessageType.DATA_READY:
        if message.subscription_ref:
            await services.fetched_delivery_service.schedule(message.subscription_ref)
        else:
            for subscription in subscriptions:
                await services.fetched_delivery_service.schedule(
                    subscription.config.subscription_ref
                )

    elif message.message_type is InboundMessageType.HEARTBEAT:
        await services.provider_monitor.record_heartbeat(
            message.subscription_ref, message.service_started_time
        )

    elif message.message_type is InboundMessageType.DELIVERY:
        if not message.subscription_ref:
            raise HTTPException(status_code=400, detail="Missing subscription reference")
        try:
            await services.delivery_service.accept(
                message.subscription_ref,
                payload,
                request.headers.get("content-type"),
                message.message_name or "Delivery",
                wait_timeout_seconds=request.app.state.settings.direct_delivery_throttle_timeout_seconds,
            )
        except DeliveryAdmissionClosedError as exc:
            raise HTTPException(
                status_code=410, detail="Subscription is terminating or has been deleted"
            ) from exc
        except (DeliveryAdmissionDeletedError, KeyError) as exc:
            raise HTTPException(status_code=404, detail="Unknown subscription") from exc
        except SpoolCapacityTimeoutError as exc:
            logger.warning(
                "Direct delivery rejected with HTTP 503 after spool throttle timeout "
                "subscription_ref=%s timeout_seconds=%s",
                message.subscription_ref,
                request.app.state.settings.direct_delivery_throttle_timeout_seconds,
            )
            raise HTTPException(
                status_code=503,
                detail="Spool capacity is currently exhausted; retry delivery later",
            ) from exc

    response_payload = profile.build_inbound_response(message, subscriptions)
    return await _xml_response(request, response_payload, subscriptions)
