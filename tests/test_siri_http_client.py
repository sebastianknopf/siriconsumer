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


@pytest.mark.asyncio
async def test_vdv_profile_uses_action_specific_publisher_urls() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path.endswith("aboverwalten.xml"):
            return httpx.Response(
                200,
                content=b'<AboAntwort><Bestaetigung Ergebnis="ok" Fehlernummer="0"/></AboAntwort>',
            )
        if request.url.path.endswith("status.xml"):
            return httpx.Response(
                200,
                content=(
                    b'<StatusAntwort><Status Ergebnis="ok"/>'
                    b'<StartDienstZst>2026-09-18T06:00:00Z</StartDienstZst></StatusAntwort>'
                ),
            )
        return httpx.Response(
            200,
            content=b'<DatenAbrufenAntwort><WeitereDaten>false</WeitereDaten></DatenAbrufenAntwort>',
        )

    subscription = SubscriptionRecord(
        config=SubscriptionCreate.model_validate(
            {
                "provider_url": "https://publisher.example/vdv/aus",
                "profile": "de-vdv",
            "version": "2",
                "service": "ET",
                "delivery_mode": "fetched",
                "requestor_ref": "consumer",
                "subscriber_ref": "consumer",
                "producer_ref": "producer-control-centre",
                "subscription_ref": "abo-1",
                "initial_termination_time": "2026-09-19T04:00:00Z",
                "sink": {"type": "directory", "path": "/tmp/vdv"},
            }
        )
    )

    client = SiriHttpClient()
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    try:
        await client.subscribe(subscription)
        await client.check_status(subscription)
        await client.fetch_delivery(subscription)
        await client.terminate(subscription)
    finally:
        await client.close()

    assert seen_paths == [
        "/vdv/aus/aboverwalten.xml",
        "/vdv/aus/status.xml",
        "/vdv/aus/datenabrufen.xml",
        "/vdv/aus/aboverwalten.xml",
    ]


@pytest.mark.asyncio
async def test_missing_mtls_file_fails_before_outbound_request(tmp_path) -> None:
    from siriconsumer.domain.exceptions import MtlsCertificateFileError

    subscription = SubscriptionRecord(
        config=SubscriptionCreate.model_validate(
            {
                "provider_url": "https://publisher.example/siri",
                "service": "VM",
                "delivery_mode": "direct",
                "requestor_ref": "consumer",
                "subscriber_ref": "consumer",
                "subscription_ref": "sub-mtls-missing",
                "mtls": {
                    "cert_filename": str(tmp_path / "missing.crt"),
                    "key_filename": str(tmp_path / "missing.key"),
                },
                "sink": {"type": "directory", "path": "/tmp/siri"},
            }
        )
    )

    client = SiriHttpClient()
    try:
        with pytest.raises(MtlsCertificateFileError, match="Configured mTLS file"):
            await client.subscribe(subscription)
    finally:
        await client.close()

@pytest.mark.asyncio
async def test_http_endpoint_disables_server_certificate_verification_with_mtls(monkeypatch) -> None:
    import ssl

    captured_verify: list[ssl.SSLContext | bool] = []

    class FakeAsyncClient:
        def __init__(self, *, timeout: float, verify: ssl.SSLContext | bool) -> None:
            captured_verify.append(verify)

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, endpoint: str, *, content: bytes, headers: dict[str, str]) -> httpx.Response:
            return httpx.Response(
                200,
                content=b'<Siri xmlns="http://www.siri.org.uk/siri"><Status>true</Status></Siri>',
            )

    subscription = SubscriptionRecord(
        config=SubscriptionCreate.model_validate(
            {
                "provider_url": "http://publisher.example/siri",
                "service": "VM",
                "delivery_mode": "direct",
                "requestor_ref": "consumer",
                "subscriber_ref": "consumer",
                "subscription_ref": "sub-http-mtls",
                "mtls": {
                    "cert_filename": "/certs/client.crt",
                    "key_filename": "/certs/client.key",
                },
                "sink": {"type": "directory", "path": "/tmp/siri"},
            }
        )
    )

    client = SiriHttpClient()
    monkeypatch.setattr(client, "_mtls_context", lambda _: ssl.create_default_context())
    monkeypatch.setattr("siriconsumer.infrastructure.siri_http_client.httpx.AsyncClient", FakeAsyncClient)

    try:
        await client.subscribe(subscription)
    finally:
        await client.close()

    assert captured_verify == [False]
