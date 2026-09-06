from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from siriconsumer.api.dependencies import AppServices
from siriconsumer.domain.models import SubscriptionCreate, SubscriptionRecord

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


def _services(request: Request) -> AppServices:
    return request.app.state.services


@router.post("", response_model=SubscriptionRecord, status_code=status.HTTP_201_CREATED)
async def create_subscription(config: SubscriptionCreate, request: Request) -> SubscriptionRecord:
    try:
        return await _services(request).subscription_manager.create(config)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Publisher subscription failed: {exc}") from exc


@router.get("", response_model=list[SubscriptionRecord])
async def list_subscriptions(request: Request) -> list[SubscriptionRecord]:
    return await _services(request).repository.list_all()


@router.get("/{subscription_id}", response_model=SubscriptionRecord)
async def get_subscription(subscription_id: UUID, request: Request) -> SubscriptionRecord:
    record = await _services(request).repository.get(subscription_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return record


@router.post("/{subscription_id}/restart", response_model=SubscriptionRecord)
async def restart_subscription(subscription_id: UUID, request: Request) -> SubscriptionRecord:
    try:
        return await _services(request).subscription_manager.recover(subscription_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Subscription not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Subscription recovery failed: {exc}") from exc


@router.delete("/{subscription_id}", response_model=SubscriptionRecord)
async def delete_subscription(subscription_id: UUID, request: Request) -> SubscriptionRecord:
    try:
        return await _services(request).subscription_manager.terminate(subscription_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Subscription not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Subscription termination failed: {exc}") from exc
