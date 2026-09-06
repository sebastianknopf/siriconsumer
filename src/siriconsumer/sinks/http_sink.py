from __future__ import annotations

import asyncio

import httpx

from siriconsumer.domain.models import HttpSinkConfig, SpoolMetadata, SubscriptionRecord


class HttpSink:
    def __init__(self, config: HttpSinkConfig) -> None:
        self._config = config
        timeout = httpx.Timeout(
            connect=config.connect_timeout_seconds,
            read=config.response_timeout_seconds,
            write=config.response_timeout_seconds,
            pool=config.connect_timeout_seconds,
        )
        self._client = httpx.AsyncClient(timeout=timeout)
        self._semaphore = asyncio.Semaphore(config.max_concurrency)

    async def write(self, subscription: SubscriptionRecord, metadata: SpoolMetadata, payload: bytes) -> None:
        headers = {
            "Content-Type": metadata.content_type or "application/xml",
            "X-Siri-Subscription-Id": str(subscription.id),
            "X-Siri-Subscription-Ref": subscription.config.subscription_ref,
            "X-Siri-Message-Id": str(metadata.message_id),
            **self._config.headers,
        }
        
        async with self._semaphore:
            response = await self._client.post(str(self._config.url), content=payload, headers=headers)
            response.raise_for_status()

    async def close(self) -> None:
        await self._client.aclose()
