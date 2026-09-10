from __future__ import annotations

import asyncio

from siriconsumer.services.communication_monitor import LiveCommunicationMonitor


def test_publish_does_not_parse_xml_without_active_connection(monkeypatch) -> None:
    monitor = LiveCommunicationMonitor()

    def fail_if_called(payload: bytes) -> str:
        raise AssertionError("XML formatting must not run without an observer")

    monkeypatch.setattr(monitor, "_pretty_xml", fail_if_called)

    monitor.publish(
        direction="incoming",
        kind="request",
        payload=b"<Siri/>",
        endpoint="http://consumer.example/siri",
    )


def test_publish_pretty_prints_one_event_for_active_connection() -> None:
    monitor = LiveCommunicationMonitor()
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    monitor._queue = queue

    monitor.publish(
        direction="outgoing",
        kind="request",
        payload=b"<Siri><CheckStatusRequest><Status>true</Status></CheckStatusRequest></Siri>",
        endpoint="https://publisher.example/siri",
    )

    event = queue.get_nowait()
    assert event["direction"] == "outgoing"
    assert event["kind"] == "request"
    assert event["endpoint"] == "https://publisher.example/siri"
    assert "\n" in str(event["xml"])
    assert "  <CheckStatusRequest>" in str(event["xml"])
