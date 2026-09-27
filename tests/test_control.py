from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from siriconsumer.api.control import router


class SubscriptionManagerStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, bool]] = []

    async def terminate(
        self, subscription_ref: str, *, force: bool = False, spool: bool = True
    ) -> None:
        self.calls.append((subscription_ref, force, spool))


def _client(manager: SubscriptionManagerStub) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.services = SimpleNamespace(subscription_manager=manager)
    return TestClient(app)


def test_delete_defaults_to_spool_drain() -> None:
    manager = SubscriptionManagerStub()

    response = _client(manager).delete("/api/subscriptions/sub-1")

    assert response.status_code == 204
    assert manager.calls == [("sub-1", False, True)]


def test_delete_accepts_spool_false_independently_of_force() -> None:
    manager = SubscriptionManagerStub()
    client = _client(manager)

    response = client.delete("/api/subscriptions/sub-1?spool=false")
    force_response = client.delete("/api/subscriptions/sub-2?force&spool=false")

    assert response.status_code == 204
    assert force_response.status_code == 204
    assert manager.calls == [
        ("sub-1", False, False),
        ("sub-2", True, False),
    ]
