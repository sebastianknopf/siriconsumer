from __future__ import annotations

import asyncio
import logging
import ssl
from contextlib import suppress

import aiomqtt

from siriconsumer.domain.models import MqttSinkConfig, SpoolMetadata, SubscriptionRecord

logger = logging.getLogger(__name__)


class MqttSink:
    """MQTT sink with one persistent connection per subscription sink instance."""

    def __init__(self, config: MqttSinkConfig) -> None:
        self._config = config
        self._client: aiomqtt.Client | None = None
        self._lock = asyncio.Lock()

    async def write(
        self,
        subscription: SubscriptionRecord,
        metadata: SpoolMetadata,
        payload: bytes,
    ) -> None:
        topic = self._config.topic.format(
            subscription_ref=subscription.config.subscription_ref,
        )

        # The spool already serializes delivery per subscription. The lock also
        # protects the client lifecycle if the sink is called from another path.
        async with self._lock:
            client = await self._ensure_connected()
            try:
                async with asyncio.timeout(self._config.publish_timeout_seconds):
                    await client.publish(
                        topic,
                        payload=payload,
                        qos=self._config.qos,
                        retain=self._config.retain,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                # A timed-out or failed QoS publish has an uncertain connection/
                # packet state. Drop the client and let the durable spool retry
                # the same message on a fresh connection.
                await self._disconnect(suppress_errors=True)
                raise

    async def close(self) -> None:
        async with self._lock:
            await self._disconnect(suppress_errors=True)

    async def _ensure_connected(self) -> aiomqtt.Client:
        if self._client is not None:
            return self._client

        password = self._config.password.get_secret_value() if self._config.password else None
        tls_context = ssl.create_default_context() if self._config.tls else None

        client = aiomqtt.Client(
            hostname=self._config.hostname,
            port=self._config.port,
            username=self._config.username,
            password=password,
            tls_context=tls_context,
        )

        try:
            async with asyncio.timeout(self._config.connect_timeout_seconds):
                await client.__aenter__()
        except asyncio.CancelledError:
            raise
        except Exception:
            # __aenter__ may have partially initialized the underlying client.
            # Best-effort cleanup prevents callbacks/socket state from surviving
            # a failed connection attempt.
            with suppress(Exception):
                async with asyncio.timeout(self._config.disconnect_timeout_seconds):
                    await client.__aexit__(None, None, None)

            raise

        self._client = client
        logger.debug(
            "MQTT connection established hostname=%s port=%s",
            self._config.hostname,
            self._config.port,
        )

        return client

    async def _disconnect(self, *, suppress_errors: bool) -> None:
        client = self._client
        self._client = None
        if client is None:
            return

        try:
            async with asyncio.timeout(self._config.disconnect_timeout_seconds):
                await client.__aexit__(None, None, None)
            logger.debug(
                "MQTT connection closed hostname=%s port=%s",
                self._config.hostname,
                self._config.port,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            if suppress_errors:
                logger.warning(
                    "MQTT disconnect cleanup failed hostname=%s port=%s",
                    self._config.hostname,
                    self._config.port,
                    exc_info=True,
                )

                return
            raise
