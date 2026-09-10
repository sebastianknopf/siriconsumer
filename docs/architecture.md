# Architecture

## Overview

The application is a single deployable container. It deliberately avoids required infrastructure services such as PostgreSQL, Redis, or an external job queue.

```text
Control Clients                  SIRI Publisher
      |                               |
      v                               v
+------------------------------------------------+
|                 FastAPI process                |
|                                                |
|  Control API        SIRI Receive API           |
|       |                    |                   |
|       v                    v                   |
|  Subscription        Durable Spool             |
|  Manager                  |                    |
|       |                   v                    |
|       |              Sink Workers              |
|       |          /       |       |      \      |
|       v         Dir     HTTP      S3     MQTT  |
|    SQLite                                      |
|       |                                        |
|  Provider Monitor                              |
+------------------------------------------------+
```

## Design Principles

The code is separated through interfaces located in `src/siriconsumer/interfaces`. Interface modules intentionally start with `intf_`. Application services depend on these abstractions instead of concrete SQLite, HTTP, filesystem, S3, or MQTT implementations.

The application uses `asyncio` for long-lived workers, provider checks, HTTP I/O, and sink delivery. XML is parsed and created with `lxml.etree`. Raw delivery payloads are never parsed and re-serialized before being spooled or forwarded.

## Runtime Components

### Control API

Manages the desired subscription set. Configuration is persisted locally before provider lifecycle operations are performed.

### SIRI Receive API

Receives `ServiceDelivery`, `DataReadyNotification`, and heartbeat/status related messages. Direct delivery payloads are durably spooled before an acknowledgement is returned. When the per-subscription spool is full, DirectDelivery applies bounded HTTP backpressure and returns 503 only if capacity does not become available before the configured throttle timeout. Fetched delivery notifications schedule a fetch operation, and `MoreData=true` responses trigger additional bounded `DataSupplyRequest` calls.

### Live Communication Monitor

A single optional WebSocket observer can connect to `/api/communication` to inspect live XML traffic in both directions. Incoming publisher callbacks and responses as well as outgoing publisher requests and SIRI acknowledgements are emitted as individual JSON events containing pretty-printed XML. The monitor has no durable storage. Its XML parser and formatter are not invoked unless a WebSocket connection is active, so normal production traffic does not pay XML pretty-printing overhead. The monitor does not write payload XML to application logs.

### Subscription Manager

Owns lifecycle transitions and applies a single recovery policy: terminate first, then recreate from stored configuration. This policy is used during consumer startup, manual restart, heartbeat failure recovery, and detected publisher restart.

### Provider Monitor

Tracks inbound heartbeat information and can actively call `CheckStatus`. If a publisher supplies `ServiceStartedTime` and that value changes, all active subscriptions for that provider are recovered.

### Durable Spool

The spool stores pending raw messages containing data besides the subscription management and heartbeat/status messages on disk. It maintains an in-memory deque per subscription with a configurable maximum of 100 pending messages by default. Capacity pressure is handled by waiting for a slot instead of evicting existing messages. DirectDelivery bounds that wait with a configurable timeout; FetchedDelivery waits until capacity becomes available. A full disk scan is used only once during startup reconstruction, and existing backlog is retained even if it exceeds a newly configured lower limit.

### Sink Workers

Workers asynchronously deliver spooled payloads to a directory, HTTP endpoint, S3 bucket, or MQTT broker or another configured sink type. Successful delivery removes the spool entry. Failed delivery is retried with bounded exponential backoff.

## Persistence

SQLite stores only subscription and provider state. The spool stores payload bytes separately. Mounting `/app/state` makes both survive container replacement.
