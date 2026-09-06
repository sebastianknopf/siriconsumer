from __future__ import annotations

from typing import Any

import pytest

aiomqtt = pytest.importorskip("aiomqtt")

from siriconsumer.domain.models import (
    MqttSinkConfig,
    SpoolMetadata,
    SubscriptionCreate,
    SubscriptionRecord,
)
from siriconsumer.sinks.mqtt_sink import MqttSink


class FakeClient:
    instances: list["FakeClient"] = []
    fail_next_publish = False

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.enter_count = 0
        self.exit_count = 0
        self.publishes: list[tuple[str, bytes, int, bool]] = []
        self.__class__.instances.append(self)

    async def __aenter__(self) -> "FakeClient":
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.exit_count += 1

    async def publish(self, topic: str, *, payload: bytes, qos: int, retain: bool) -> None:
        if self.__class__.fail_next_publish:
            self.__class__.fail_next_publish = False
            raise RuntimeError("publish failed")
        self.publishes.append((topic, payload, qos, retain))


def _subscription(config: MqttSinkConfig) -> SubscriptionRecord:
    return SubscriptionRecord(
        config=SubscriptionCreate.model_validate(
            {
                "provider_url": "https://publisher.example/siri",
                "service": "VM",
                "delivery_mode": "direct",
                "requestor_ref": "consumer",
                "subscriber_ref": "subscriber",
                "subscription_ref": "sub-1",
                "sink": config.model_dump(),
            }
        )
    )


@pytest.mark.asyncio
async def test_mqtt_sink_reuses_connection_for_multiple_messages(monkeypatch) -> None:
    FakeClient.instances.clear()
    monkeypatch.setattr(aiomqtt, "Client", FakeClient)
    config = MqttSinkConfig(
        hostname="mqtt.example.com",
        username="user",
        password="secret",
        qos=1,
    )
    subscription = _subscription(config)
    sink = MqttSink(config)

    await sink.write(
        subscription,
        SpoolMetadata(subscription_id=subscription.id, subscription_ref="sub-1"),
        b"first",
    )
    await sink.write(
        subscription,
        SpoolMetadata(subscription_id=subscription.id, subscription_ref="sub-1"),
        b"second",
    )

    assert len(FakeClient.instances) == 1
    client = FakeClient.instances[0]
    assert client.enter_count == 1
    assert client.exit_count == 0
    assert [item[1] for item in client.publishes] == [b"first", b"second"]
    assert client.kwargs["password"] == "secret"

    await sink.close()
    assert client.exit_count == 1


@pytest.mark.asyncio
async def test_mqtt_sink_discards_failed_connection_and_reconnects(monkeypatch) -> None:
    FakeClient.instances.clear()
    FakeClient.fail_next_publish = True
    monkeypatch.setattr(aiomqtt, "Client", FakeClient)
    config = MqttSinkConfig(hostname="mqtt.example.com")
    subscription = _subscription(config)
    sink = MqttSink(config)
    metadata = SpoolMetadata(subscription_id=subscription.id, subscription_ref="sub-1")

    with pytest.raises(RuntimeError, match="publish failed"):
        await sink.write(subscription, metadata, b"first")

    assert len(FakeClient.instances) == 1
    assert FakeClient.instances[0].exit_count == 1

    await sink.write(subscription, metadata, b"retry")
    assert len(FakeClient.instances) == 2
    assert FakeClient.instances[1].publishes[0][1] == b"retry"

    await sink.close()
