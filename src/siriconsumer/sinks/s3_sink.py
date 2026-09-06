from __future__ import annotations

import aioboto3

from siriconsumer.domain.models import S3SinkConfig, SpoolMetadata, SubscriptionRecord


class S3Sink:
    def __init__(self, config: S3SinkConfig) -> None:
        self._config = config
        self._session = aioboto3.Session()

    async def write(self, subscription: SubscriptionRecord, metadata: SpoolMetadata, payload: bytes) -> None:
        prefix = self._config.prefix.rstrip("/")
        key = (
            f"{prefix}/subscription={subscription.config.subscription_ref}/"
            f"{metadata.received_at:%Y/%m/%d/%H}/"
            f"{metadata.received_at.strftime('%Y%m%dT%H%M%S.%fZ')}_{metadata.message_id}.xml"
        )

        kwargs: dict[str, object] = {}
        if self._config.region_name:
            kwargs["region_name"] = self._config.region_name
        if self._config.endpoint_url:
            kwargs["endpoint_url"] = str(self._config.endpoint_url)

        async with self._session.client("s3", **kwargs) as client:
            await client.put_object(
                Bucket=self._config.bucket,
                Key=key,
                Body=payload,
                ContentType=metadata.content_type or "application/xml",
                Metadata={
                    "subscription-ref": subscription.config.subscription_ref,
                    "message-id": str(metadata.message_id),
                    "received-at": metadata.received_at.isoformat(),
                },
            )

    async def close(self) -> None:
        return None
