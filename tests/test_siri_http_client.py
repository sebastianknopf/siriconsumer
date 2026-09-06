from __future__ import annotations

import httpx
import pytest

from siriconsumer.domain.models import SubscriptionCreate, SubscriptionRecord
from siriconsumer.infrastructure.siri_http_client import SiriHttpClient


@pytest.mark.asyncio
async def test_subscription_headers_are_sent_with_every_publisher_request() -> None:
    seen_headers: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers)
        return httpx.Response(
            200,
            content=b'<Siri xmlns="http://www.siri.org.uk/siri"><Status>true</Status></Siri>',
        )

    subscription = SubscriptionRecord(
        config=SubscriptionCreate.model_validate(
            {
                "provider_url": "https://publisher.example/siri",
                "service": "VM",
                "delivery_mode": "fetched",
                "requestor_ref": "consumer",
                "subscriber_ref": "consumer",
                "subscription_ref": "sub-1",
                "headers": {
                    "Authorization": "Bearer secret-token",
                    "X-Tenant": "tenant-a",
                    "Content-Type": "application/vnd.siri+xml",
                },
                "sink": {"type": "directory", "path": "/tmp/siri"},
            }
        )
    )

    client = SiriHttpClient()
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    try:
        await client.subscribe(subscription)
        await client.terminate(subscription)
        await client.check_status(subscription)
        await client.fetch_delivery(subscription)
    finally:
        await client.close()

    assert len(seen_headers) == 4
    for headers in seen_headers:
        assert headers["Authorization"] == "Bearer secret-token"
        assert headers["X-Tenant"] == "tenant-a"
        assert headers["Content-Type"] == "application/vnd.siri+xml"


def test_subscription_request_contains_requested_heartbeat_interval() -> None:
    subscription = SubscriptionRecord(
        config=SubscriptionCreate.model_validate(
            {
                "provider_url": "https://publisher.example/siri",
                "service": "VM",
                "delivery_mode": "direct",
                "requestor_ref": "consumer",
                "subscriber_ref": "consumer",
                "subscription_ref": "sub-heartbeat",
                "heartbeat": {"enabled": True, "interval": "PT45S"},
                "sink": {"type": "directory", "path": "/tmp/siri"},
            }
        )
    )

    client = SiriHttpClient()
    payload = client._build_subscription_request(subscription)

    assert b"<HeartbeatInterval>PT45S</HeartbeatInterval>" in payload


def test_subscription_request_omits_heartbeat_context_when_disabled() -> None:
    subscription = SubscriptionRecord(
        config=SubscriptionCreate.model_validate(
            {
                "provider_url": "https://publisher.example/siri",
                "service": "VM",
                "delivery_mode": "direct",
                "requestor_ref": "consumer",
                "subscriber_ref": "consumer",
                "subscription_ref": "sub-no-heartbeat",
                "heartbeat": {"enabled": False},
                "sink": {"type": "directory", "path": "/tmp/siri"},
            }
        )
    )

    client = SiriHttpClient()
    payload = client._build_subscription_request(subscription)

    assert b"HeartbeatInterval" not in payload
    assert b"SubscriptionContext" not in payload
