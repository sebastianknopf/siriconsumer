from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal, Union
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
    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    publish_timeout_seconds: float = Field(default=30.0, gt=0)
    disconnect_timeout_seconds: float = Field(default=5.0, gt=0)


SinkConfig = Annotated[
    Union[DirectorySinkConfig, HttpSinkConfig, S3SinkConfig, MqttSinkConfig],
    Field(discriminator="type"),
]


class MtlsConfig(BaseModel):
    cert_filename: str = Field(
        min_length=1,
        description="Client certificate file used for outbound producer requests.",
    )
    key_filename: str = Field(
        min_length=1,
        description="Private key file used for outbound producer requests.",
    )


class CommunicationProfileInfo(BaseModel):
    profile: str
    version: str
    specification: str
    supported_services: list[str]
    supported_parameters: dict[str, list[str]] = Field(default_factory=dict)


class SubscriptionCreate(BaseModel):
    provider_url: AnyHttpUrl
    profile: str = Field(
        default="default",
        min_length=1,
        description="Communication profile. Defaults to standard SIRI.",
    )
    version: str = Field(
        default="default",
        min_length=1,
        description="Communication profile version. Defaults to the default profile version.",
    )
    service: str = Field(
        min_length=1,
        description="Service code interpreted by the selected profile.",
    )
    delivery_mode: DeliveryMode
    requestor_ref: str
    subscriber_ref: str
    producer_ref: str | None = Field(
        default=None,
        description=(
            "Producer identifier used by profiles that require an agreed remote "
            "control-centre identifier."
        ),
    )
    subscription_ref: str = Field(min_length=1)
    request_timestamp: datetime | None = None
    consumer_address: AnyHttpUrl | None = None
    preview_interval: str = Field(default="PT2H")
    initial_termination_time: datetime | None = None
    incremental_updates: bool = True
    change_before_updates: str = Field(default="PT30S")
    headers: dict[str, str] = Field(default_factory=dict)
    mtls: MtlsConfig | None = Field(
        default=None,
        description="Optional client certificate and key for outbound producer requests only.",
    )
    logging: bool = Field(
        default=False,
        description="Persist pretty-printed XML communication for this subscription.",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Profile-specific subscription parameters.",
    )
    filters: SubscriptionFilters = Field(default_factory=SubscriptionFilters)
    subscription_policy: SubscriptionPolicy = Field(default_factory=SubscriptionPolicy)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    sink: SinkConfig


class SubscriptionRecord(BaseModel):
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
    subscription_ref: str
    received_at: datetime = Field(default_factory=utc_now)
    content_type: str | None = None
    message_type: str | None = None
    retry_count: int = Field(default=0, ge=0)


class SpoolEntry(BaseModel):
    metadata: SpoolMetadata
    payload_path: Path
    metadata_path: Path
