# Delivery, Spool, and Sinks

## Durable Acceptance

Incoming payloads are accepted in two stages:

1. Write the exact HTTP body bytes to the local durable spool.
2. Return the SIRI acknowledgement.

Sink delivery happens asynchronously afterward. A slow downstream HTTP service therefore does not keep the publisher request open after the spool write has completed.

Delivery is strictly sequential per subscription. Only the oldest pending message of a subscription is eligible for delivery. Once a worker claims a message, that message is in-flight and protected from subscription purge until sink processing finishes. The next message for the same subscription is released only after the in-flight message succeeds or is permanently dropped after exhausting its sink retry budget. Different subscriptions can still be delivered in parallel by different workers.

A failed sink delivery is retried at most five times by default, in addition to the initial attempt. Retry count is persisted in spool metadata, so a graceful restart does not reset the retry budget. Exponential backoff is bounded by the configured retry delay settings. After the retry budget is exhausted, the message is deleted from the spool and a warning is logged.

## Spool Capacity and DirectDelivery Backpressure

Each subscription has a configurable maximum pending-message count. The default and intended production setting is 100.

At runtime the spool maintains:

```text
dict[subscription_ref, deque[SpoolEntry]]
```

The deque is ordered oldest to newest. The configured limit applies to pending messages, not to the single in-flight message. An in-flight message therefore does not consume one of the configured pending slots.

Messages are never evicted to make room for newer messages. When the pending limit is reached, writers wait until a sink worker claims or removes an entry and capacity becomes available. This keeps already accepted data durable and preserves FIFO ordering.

For inbound DirectDelivery requests, the wait is bounded by `SIRI_DIRECT_DELIVERY_THROTTLE_TIMEOUT_SECONDS`, which defaults to 5 seconds. If no slot becomes available within that interval, `/siri` returns HTTP 503 and logs a warning. Normal throttling that resolves before the timeout is not logged as a warning.

FetchedDelivery writes use the same capacity gate without the DirectDelivery HTTP timeout. A fetch worker waits for spool capacity rather than discarding an already fetched response.

The filesystem is scanned exactly once during application startup to reconstruct the in-memory index. Existing backlog is never deleted merely because it exceeds a subsequently lowered configured limit. New writes remain throttled until the pending count falls below the configured limit.

## DirectDelivery During Subscription Termination

Inbound DirectDelivery uses a per-subscription admission lease. The lease is acquired before the subscription is resolved and before spool capacity is awaited. This creates a deterministic cut-off when a subscription is deleted:

- A request that acquired its lease before termination started is considered accepted for processing and may finish.
- A request arriving after the admission gate is closed but before durable deletion completes is rejected with HTTP 410 and never enters the spool.
- After the SQLite subscription row is deleted, subsequent callbacks for that `subscription_ref` return HTTP 404. The 410 response is therefore limited to the active termination window.
- If a pre-cut-off request was throttled because the spool was full when termination begins, its normal `SIRI_DIRECT_DELIVERY_THROTTLE_TIMEOUT_SECONDS` deadline is disabled. It keeps waiting for capacity so a request already submitted by the publisher is not lost merely because termination started concurrently.
- The subscription remains in SQLite until all admitted inbound requests have finished and the subscription spool has drained completely through the sink. Only then is the database row deleted and the cached sink closed.

This ordering prevents late `last_message_at` updates against a deleted database row and prevents orphaned spool entries whose subscription no longer exists.

## FetchedDelivery and MoreData

A `DataReadyNotification` schedules a `DataSupplyRequest`. The raw response is durably spooled as a `DataSupplyResponse` payload.

If the response contains `MoreData=true` or `MoreData=1`, the same fetch worker immediately issues another `DataSupplyRequest` for the subscription. Each response is independently spooled in request order. Fetching continues until `MoreData` is false or absent.

`SIRI_FETCHED_DELIVERY_MAX_MORE_DATA_REQUESTS` limits the number of additional requests that may be triggered by `MoreData=true` after the initial `DataSupplyRequest`. The default is 100. A value of 0 disables additional `MoreData` requests. If the producer still reports `MoreData=true` when the configured limit is reached, the loop stops and a warning is logged. Normal `MoreData` processing does not produce warnings.

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
