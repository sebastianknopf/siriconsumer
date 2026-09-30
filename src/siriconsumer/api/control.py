from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from typing import Annotated

from siriconsumer.api.dependencies import AppServices
from siriconsumer.domain.models import SubscriptionCreate, SubscriptionRecord
from siriconsumer.interfaces.intf_subscription_repository import SubscriptionAlreadyExistsError

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


def _services(request: Request) -> AppServices:
    return request.app.state.services


@router.post("", response_model=SubscriptionRecord, status_code=status.HTTP_201_CREATED)
async def create_subscription(config: SubscriptionCreate, request: Request) -> SubscriptionRecord:
    try:
        return await _services(request).subscription_manager.create(config)
    except SubscriptionAlreadyExistsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Publisher subscription failed: {exc}") from exc


@router.get("", response_model=list[SubscriptionRecord])
async def list_subscriptions(request: Request) -> list[SubscriptionRecord]:
    return await _services(request).repository.list_all()


@router.get("/{subscription_ref}", response_model=SubscriptionRecord)
async def get_subscription(subscription_ref: str, request: Request) -> SubscriptionRecord:
    record = await _services(request).repository.get(subscription_ref)
    if record is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return record


@router.post("/{subscription_ref}/restart", response_model=SubscriptionRecord)
async def restart_subscription(subscription_ref: str, request: Request) -> SubscriptionRecord:
    try:
        return await _services(request).subscription_manager.recover(subscription_ref)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Subscription not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Subscription recovery failed: {exc}") from exc


@router.delete("/{subscription_ref}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(
    subscription_ref: str,
    request: Request,
    spool: Annotated[
        bool,
        Query(
            description=(
                "Whether queued spool entries must be delivered before the "
                "subscription is deleted. Set to false to discard pending "
                "entries after any in-flight delivery has completed."
            ),
        ),
    ] = True,
    force: Annotated[
        str | None,
        Query(
            description=(
                "Force local termination even if the producer termination "
                "request fails. Presence of this parameter enables force mode."
            ),
        ),
    ] = None,
) -> None:
    force_enabled = force is not None

    try:
        await _services(request).subscription_manager.terminate(
            subscription_ref,
            force=force_enabled,
            spool=spool,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Subscription not found",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Subscription termination failed: {exc}",
        ) from exc
