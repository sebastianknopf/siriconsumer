from __future__ import annotations

from uuid import UUID

from siriconsumer.domain.enums import SinkType
from siriconsumer.domain.models import (
    DirectorySinkConfig,
    HttpSinkConfig,
    MqttSinkConfig,
    S3SinkConfig,
    SubscriptionRecord,
)
from siriconsumer.interfaces.intf_message_sink import MessageSink
from siriconsumer.sinks.directory_sink import DirectorySink
from siriconsumer.sinks.http_sink import HttpSink
from siriconsumer.sinks.mqtt_sink import MqttSink
from siriconsumer.sinks.s3_sink import S3Sink


class DefaultSinkFactory:
    def __init__(self) -> None:
        self._instances: dict[UUID, MessageSink] = {}

    def get(self, subscription: SubscriptionRecord) -> MessageSink:
        existing = self._instances.get(subscription.id)
        if existing is not None:
            return existing

        config = subscription.config.sink
        if config.type is SinkType.DIRECTORY and isinstance(config, DirectorySinkConfig):
            sink: MessageSink = DirectorySink(config)
        elif config.type is SinkType.HTTP and isinstance(config, HttpSinkConfig):
            sink = HttpSink(config)
        elif config.type is SinkType.S3 and isinstance(config, S3SinkConfig):
            sink = S3Sink(config)
        elif config.type is SinkType.MQTT and isinstance(config, MqttSinkConfig):
            sink = MqttSink(config)
        else:
            raise ValueError(f"Unsupported sink configuration: {config.type}")

        self._instances[subscription.id] = sink

        return sink

    async def close(self) -> None:
        for sink in self._instances.values():
            await sink.close()

        self._instances.clear()
