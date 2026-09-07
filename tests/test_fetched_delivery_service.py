from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from siriconsumer.services.fetched_delivery_service import FetchedDeliveryService


def _payload(more_data: bool | None) -> bytes:
    if more_data is None:
        field = ""
    else:
        field = f"<MoreData>{str(more_data).lower()}</MoreData>"
    return (
        '<Siri xmlns="http://www.siri.org.uk/siri">'
        f"<ServiceDelivery>{field}</ServiceDelivery>"
        "</Siri>"
    ).encode()


@pytest.mark.asyncio
async def test_fetched_delivery_continues_while_more_data_is_true() -> None:
    subscription = SimpleNamespace(config=SimpleNamespace(subscription_ref="sub-1"))
    repository = SimpleNamespace(get=AsyncMock(return_value=subscription))
    siri_client = SimpleNamespace(
        fetch_delivery=AsyncMock(side_effect=[_payload(True), _payload(True), _payload(False)])
    )
    delivery_service = SimpleNamespace(accept=AsyncMock())
    service = FetchedDeliveryService(
        repository,
        siri_client,
        delivery_service,
        max_more_data_requests=10,
    )

    await service.start(workers=1)
    try:
        await service.schedule("sub-1")
        for _ in range(100):
            if siri_client.fetch_delivery.await_count == 3:
                break
            await asyncio.sleep(0.01)
    finally:
        await service.stop()

    assert siri_client.fetch_delivery.await_count == 3
    assert delivery_service.accept.await_count == 3


@pytest.mark.asyncio
async def test_fetched_delivery_stops_after_configured_more_data_request_limit(caplog) -> None:
    subscription = SimpleNamespace(config=SimpleNamespace(subscription_ref="sub-1"))
    repository = SimpleNamespace(get=AsyncMock(return_value=subscription))
    siri_client = SimpleNamespace(fetch_delivery=AsyncMock(return_value=_payload(True)))
    delivery_service = SimpleNamespace(accept=AsyncMock())
    service = FetchedDeliveryService(
        repository,
        siri_client,
        delivery_service,
        max_more_data_requests=2,
    )

    await service.start(workers=1)
    try:
        await service.schedule("sub-1")
        for _ in range(100):
            if siri_client.fetch_delivery.await_count == 3:
                break
            await asyncio.sleep(0.01)
    finally:
        await service.stop()

    assert siri_client.fetch_delivery.await_count == 3
    assert delivery_service.accept.await_count == 3
    assert "MoreData loop stopped at configured limit" in caplog.text


def test_has_more_data_accepts_true_and_one() -> None:
    assert FetchedDeliveryService._has_more_data(_payload(True)) is True
    assert FetchedDeliveryService._has_more_data(
        b'<Siri xmlns="http://www.siri.org.uk/siri"><MoreData>1</MoreData></Siri>'
    ) is True
    assert FetchedDeliveryService._has_more_data(_payload(False)) is False
    assert FetchedDeliveryService._has_more_data(_payload(None)) is False
