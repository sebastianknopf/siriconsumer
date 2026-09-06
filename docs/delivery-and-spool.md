# Delivery, Spool, and Sinks

## Durable Acceptance

Incoming payloads are accepted in two stages:

1. Write the exact HTTP body bytes to the local durable spool.
2. Return the SIRI acknowledgement.

Sink delivery happens asynchronously afterward. A slow downstream HTTP service therefore does not keep the publisher request open after the spool write has completed.

## Spool Limit

Each subscription has a configurable maximum pending-message count. The default and intended production setting is 100.

At runtime the spool maintains:

```text
dict[subscription_id, deque[SpoolEntry]]
```

The deque is ordered oldest to newest. Adding the 101st message removes the oldest entry from the left side and deletes its spool file before appending the new entry. No directory traversal is required during normal message ingestion.

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
