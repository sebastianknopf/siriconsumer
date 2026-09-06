from enum import StrEnum


class DeliveryMode(StrEnum):
    DIRECT = "direct"
    FETCHED = "fetched"


class SubscriptionStatus(StrEnum):
    CREATING = "creating"
    ACTIVE = "active"
    DEGRADED = "degraded"
    TERMINATING = "terminating"
    TERMINATED = "terminated"
    FAILED = "failed"


class SinkType(StrEnum):
    DIRECTORY = "directory"
    HTTP = "http"
    S3 = "s3"
    MQTT = "mqtt"
