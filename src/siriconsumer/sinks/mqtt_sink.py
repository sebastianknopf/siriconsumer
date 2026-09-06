from __future__ import annotations

import ssl

import aiomqtt

from siriconsumer.domain.models import MqttSinkConfig, SpoolMetadata, SubscriptionRecord


class MqttSink:
    def __init__(self, config: MqttSinkConfig) -> None:
        self._config = config

    async def write(self, subscription: SubscriptionRecord, metadata: SpoolMetadata, payload: bytes) -> None:
        topic = self._config.topic.format(
            subscription_ref=subscription.config.subscription_ref,
            subscription_id=subscription.id,
        )

        tls_context = ssl.create_default_context() if self._config.tls else None

        password = self._config.password.get_secret_value() if self._config.password else None

        async with aiomqtt.Client(
            hostname=self._config.hostname,
            port=self._config.port,
            username=self._config.username,
            password=password,
            tls_context=tls_context,
        ) as client:
            await client.publish(
                topic,
                payload=payload,
                qos=self._config.qos,
                retain=self._config.retain,
            )

    async def close(self) -> None:
        return None
