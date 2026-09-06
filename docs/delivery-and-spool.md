# Delivery, Spool, and Sinks

## Durable Acceptance

Incoming payloads are accepted in two stages:

1. Write the exact HTTP body bytes to the local durable spool.
2. Return the SIRI acknowledgement.

Sink delivery happens asynchronously afterward. A slow downstream HTTP service therefore does not keep the publisher request open after the spool write has completed.

Delivery is strictly sequential per subscription. Only the oldest pending message of a subscription is eligible for delivery. Once a worker claims a message, that message is in-flight and protected from spool-limit eviction and subscription purge until sink processing finishes. The next message for the same subscription is released only after the in-flight message succeeds or is permanently dropped. Different subscriptions can still be delivered in parallel by different workers.

A failed sink delivery is retried at most five times by default, in addition to the initial attempt. Retry count is persisted in spool metadata, so a graceful restart does not reset the retry budget. Exponential backoff is bounded by the configured retry delay settings. After the retry budget is exhausted, the message is deleted from the spool and a warning is logged.

## Spool Limit

Each subscription has a configurable maximum pending-message count. The default and intended production setting is 100.

At runtime the spool maintains:

```text
dict[subscription_ref, deque[SpoolEntry]]
```

The deque is ordered oldest to newest. The configured limit applies to pending messages, not to the single in-flight message. Adding a message beyond the pending limit removes the oldest non-in-flight entry and deletes its spool files before appending the new entry. An in-flight head is never selected for eviction. This remains O(1) and requires no directory traversal during normal message ingestion.

The filesystem is scanned exactly once during application startup to reconstruct the in-memory index. If more than the configured limit is found for a subscription, the oldest entries are discarded during reconstruction.

Dropped messages are logged prominently. A production deployment should also export a metric or log alert for this condition.

## Directory Sink

Writes the raw payload to the configured mounted directory. Atomic replacement is used to avoid exposing half-written files.

## HTTP Sink

Uses asynchronous HTTP requests with connection and response timeouts. A semaphore limits concurrent sends. Slow endpoints consume worker capacity but do not block the FastAPI event loop or the original SIRI request. Failed transient deliveries remain in the spool and are retried.

## S3 Sink

Uploads the raw bytes as an object. AWS credentials may be provided through the standard SDK environment, task role, instance profile, or explicit endpoint configuration for S3-compatible storage.

## MQTT Sink

Publishes the raw payload bytes to a configured topic. QoS 1 is the recommended default, giving at-least-once semantics. The spool entry is removed only after the publish operation completes successfully, so consumers should tolerate duplicate messages.

Each MQTT sink instance keeps one connection open for its subscription and reuses it for consecutive messages. A burst of pending messages therefore does not reconnect between publishes. The connection is closed during application shutdown. If connect or publish fails, or if the configured timeout expires, the client is discarded and the durable spool retries the same message using a fresh connection.

MQTT sink timeout settings:

- `connect_timeout_seconds`: maximum time for establishing the broker connection, default 10 seconds.
- `publish_timeout_seconds`: maximum time for one publish operation, including the QoS acknowledgement, default 30 seconds.
- `disconnect_timeout_seconds`: maximum time allowed for best-effort disconnect cleanup, default 5 seconds.
