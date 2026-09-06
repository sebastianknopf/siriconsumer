from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal, Union
from uuid import UUID, uuid4

from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr

from siriconsumer.domain.enums import DeliveryMode, SinkType, SubscriptionStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SubscriptionFilters(BaseModel):
    lines: list[str] = Field(default_factory=list)
    operators: list[str] = Field(default_factory=list)


class SubscriptionPolicy(BaseModel):
    update_interval: str | None = Field(
        default=None,
        description="Requested ISO-8601 minimum update interval, for example PT30S.",
    )


class HeartbeatConfig(BaseModel):
    enabled: bool = True
    interval: str = Field(
        default="PT1M",
        min_length=1,
        description=(
            "Requested ISO-8601 heartbeat interval sent as "
            "SubscriptionContext/HeartbeatInterval."
        ),
    )
    timeout_seconds: int = Field(default=180, ge=1)
    check_status_enabled: bool = True


class DirectorySinkConfig(BaseModel):
    type: Literal[SinkType.DIRECTORY] = SinkType.DIRECTORY
    path: Path


class HttpSinkConfig(BaseModel):
    type: Literal[SinkType.HTTP] = SinkType.HTTP
    url: AnyHttpUrl
    connect_timeout_seconds: float = Field(default=3.0, gt=0)
    response_timeout_seconds: float = Field(default=15.0, gt=0)
    max_concurrency: int = Field(default=8, ge=1, le=128)
    headers: dict[str, str] = Field(default_factory=dict)


class S3SinkConfig(BaseModel):
    type: Literal[SinkType.S3] = SinkType.S3
    bucket: str
    prefix: str = "incoming/"
    region_name: str | None = None
    endpoint_url: AnyHttpUrl | None = None


class MqttSinkConfig(BaseModel):
    type: Literal[SinkType.MQTT] = SinkType.MQTT
    hostname: str
    port: int = Field(default=1883, ge=1, le=65535)
    topic: str = "siri/messages/{subscription_ref}"
    qos: Literal[0, 1, 2] = 1
    retain: bool = False
    username: str | None = None
    password: SecretStr | None = None
    tls: bool = False


SinkConfig = Annotated[
    Union[DirectorySinkConfig, HttpSinkConfig, S3SinkConfig, MqttSinkConfig],
    Field(discriminator="type"),
]


class SubscriptionCreate(BaseModel):
    provider_url: AnyHttpUrl
    service: str = Field(min_length=1, description="SIRI service code, for example VM or SX.")
    delivery_mode: DeliveryMode
    requestor_ref: str
    subscriber_ref: str
    subscription_ref: str
    consumer_address: AnyHttpUrl | None = None
    initial_termination_time: datetime | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    filters: SubscriptionFilters = Field(default_factory=SubscriptionFilters)
    subscription_policy: SubscriptionPolicy = Field(default_factory=SubscriptionPolicy)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    sink: SinkConfig


class SubscriptionRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    config: SubscriptionCreate
    status: SubscriptionStatus = SubscriptionStatus.CREATING
    last_heartbeat_at: datetime | None = None
    last_message_at: datetime | None = None
    last_service_started_time: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_error: str | None = None


class SpoolMetadata(BaseModel):
    message_id: UUID = Field(default_factory=uuid4)
    subscription_id: UUID
    subscription_ref: str
    received_at: datetime = Field(default_factory=utc_now)
    content_type: str | None = None
    message_type: str | None = None


class SpoolEntry(BaseModel):
    metadata: SpoolMetadata
    payload_path: Path
    metadata_path: Path
