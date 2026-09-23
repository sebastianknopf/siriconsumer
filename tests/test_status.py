from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from siriconsumer.api.status import router
from siriconsumer.domain.enums import SubscriptionStatus
from siriconsumer.domain.models import SubscriptionCreate, SubscriptionRecord


class RepositoryStub:
    async def list_all(self) -> list[SubscriptionRecord]:
        config = SubscriptionCreate.model_validate({
            "provider_url": "https://producer.example/siri",
            "service": "ET",
            "delivery_mode": "direct",
            "requestor_ref": "consumer",
            "subscriber_ref": "consumer",
            "subscription_ref": "sub-1",
            "initial_termination_time": "2026-09-22T10:00:00Z",
            "sink": {"type": "directory", "path": "/tmp/out"},
        })
        return [SubscriptionRecord(
            config=config,
            status=SubscriptionStatus.ACTIVE,
            last_message_at=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
            last_heartbeat_at=datetime(2026, 9, 21, 12, 1, tzinfo=timezone.utc),
        )]


class SpoolStub:
    def payload_size_bytes(self, subscription_ref: str) -> int:
        assert subscription_ref == "sub-1"
        return 1536

    def pending_count(self, subscription_ref: str) -> int:
        assert subscription_ref == "sub-1"
        return 3


def test_status_page_contains_subscription_and_payload_only_spool_size() -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.services = SimpleNamespace(repository=RepositoryStub(), spool=SpoolStub())
    response = TestClient(app).get("/status")
    assert response.status_code == 200
    assert "sub-1" in response.text
    assert "default" in response.text
    assert "1.5 KiB / 3" in response.text
    assert "Spool Size shows payload bytes / data files only" in response.text
    assert 'content="5"' in response.text
    assert "Status overview" not in response.text
    assert "Version " in response.text
    assert "Last Data Received" in response.text
