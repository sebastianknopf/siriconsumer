# Subscription Lifecycle

## States

The implementation uses the following high-level states:

- `creating`
- `active`
- `degraded`
- `terminating`
- `failed`


## Subscription Identity

`subscription_ref` is the single subscription identity used by the control API, SQLite repository, SIRI messages, durable spool, delivery workers, and sink cache. It is supplied by the API client when the subscription is created and is persisted as the primary key of the `subscriptions` table.

A `subscription_ref` can exist only once in the database, regardless of subscription status. Attempting to create another subscription with the same ref is rejected with HTTP 400 and an explanatory error. There is no separate internal subscription ID.

## Recovery Policy

Recovery is intentionally deterministic. The consumer does not trust that a previously active publisher-side subscription still exists after either side restarts.

For every subscription that must be recovered:

1. Send a termination request using the stored subscription references.
2. Ignore an "unknown subscription" result as a successful cleanup condition.
3. Send a fresh subscription request using the same stored configuration.
4. Persist the active state only after a successful response.

The same procedure is used for:

- Consumer startup.
- Manual `POST /api/subscriptions/{subscription_ref}/restart`.
- Publisher restart detection.
- Heartbeat/status monitoring that concludes the subscription must be recreated.

## Termination and Deletion

A successful `DELETE /api/subscriptions/{subscription_ref}` has no durable terminated state. The consumer first asks the publisher to terminate the subscription. After that succeeds, the SQLite row is deleted, all spool entries for the subscription are purged, and any cached sink instance is closed and removed. The same `subscription_ref` can then be created again.

If publisher termination fails, the subscription remains persisted with status `failed` and its spool/sink state is retained so the failure is visible and recoverable.

## Concurrent Runtime Updates

Subscription lifecycle state and runtime observation timestamps are persisted independently. Lifecycle transitions such as `creating`, `active`, `degraded`, `terminating`, and `failed` update only the `status` and `last_error` columns. Inbound delivery, heartbeat, and active status-check paths update only their respective timestamp columns.

This separation prevents a stale `SubscriptionRecord` loaded by an inbound VM or other SIRI delivery from overwriting a newer lifecycle state. In particular, a delivery that arrives while a subscription request is still completing can update `last_message_at` without changing an `active` state that was persisted concurrently. The same rule applies to heartbeat and `ServiceStartedTime` updates.

## Publisher Restart Detection

When available, `ServiceStartedTime` is treated as a publisher-instance marker. It may be learned from inbound heartbeat/status messages or active `CheckStatus` responses. A change from the last persisted value indicates a publisher restart and triggers recovery of all subscriptions using that provider URL.

If a publisher does not provide `ServiceStartedTime`, heartbeat timeout or active health-check failure can mark subscriptions degraded, but that signal is inherently less precise than an explicit start-time change.

## Filters

The public model supports optional `lines` and `operators` lists from the start. The generic XML builder maps them into service request structures where practical. Real SIRI deployments differ, so provider/service-specific builders can validate or override this mapping behind the SIRI client interface.

## Consumer Address

`consumer_address` is optional. If omitted, the configured provider may infer or preconfigure the callback endpoint. For direct delivery, deployments commonly need a callback address that is reachable from the publisher.

## Update Interval

`subscription_policy.update_interval` accepts an ISO-8601 duration such as `PT30S`. It represents the requested minimum interval between publisher updates where the selected SIRI service and publisher support such a field. It is not a local rate limiter and cannot force a non-compliant publisher to wait.


## Publisher Request Headers

`headers` accepts arbitrary HTTP headers for a subscription. Every outbound request to that SIRI publisher for the subscription, including subscribe, terminate, active `CheckStatus`, and fetched `DataSupplyRequest` calls, includes those headers. Header names and values are persisted with the subscription configuration and reused during recovery. A configured `Content-Type` header overrides the default `application/xml` value.


## Heartbeats and Active Status Checks

Heartbeat behavior is configured per subscription under `heartbeat`. When `enabled` is `true`,
the subscription request includes `SubscriptionContext/HeartbeatInterval` using the configured
ISO-8601 `interval` value. This asks the SIRI publisher to send `HeartbeatNotification` messages
to the consumer. SIRI does not define a consumer-to-publisher `HeartbeatRequest`; heartbeat
notifications flow from publisher to consumer.

`check_status_enabled` independently controls whether the consumer sends active
`CheckStatusRequest` messages for that subscription. Set it to `false` when publisher heartbeats
should be used without active status polling. `timeout_seconds` controls how long an enabled
heartbeat may be absent before publisher recovery is triggered after at least one heartbeat has
been observed.
