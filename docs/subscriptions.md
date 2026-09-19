# Subscription Lifecycle

## States

The implementation uses the following high-level states:

- `creating`
- `active`
- `degraded`
- `terminating`
- `failed`



## Subscription Parameters

The following table describes the generic fields accepted by `POST /api/subscriptions`. Profile-specific keys inside `parameters` are intentionally not listed here; see the documentation for the selected profile under `docs/profiles/`.

| Property | Description | Examples |
| --- | --- | --- |
| `provider_url` | URL of the producer. Its exact interpretation is profile-specific. The default profile uses it as the SIRI endpoint; other profiles may use it as the base for action-specific producer URLs. | `"https://producer.example/siri"` |
| `profile` | Communication profile identifier. Defaults to `default`. Profile and version are selected independently. | `"default"`, `"de-vdv"` |
| `version` | Version of the selected communication profile. Defaults to `default`. | `"default"`, `"2"` |
| `service` | SIRI service code exposed by the public API. Profiles map this code to their protocol-specific service where required. | `"ET"`, `"PT"`, `"VM"` |
| `delivery_mode` | Delivery mode used by the subscription. | `"direct"`, `"fetched"` |
| `requestor_ref` | Identifier of the requesting consumer. Profiles may map this to their corresponding consumer/sender identifier. | `"MY-CONSUMER"` |
| `subscriber_ref` | SIRI subscriber reference. It remains a generic subscription field even when a selected profile does not use it. | `"MY-SUBSCRIBER"` |
| `producer_ref` | Optional identifier of the remote producer. Profiles can require it for routing or protocol-specific addressing. | `"PRODUCER-LEIPZIG"` |
| `subscription_ref` | Unique subscription identity inside the consumer. It is also used as the protocol subscription identifier where the selected profile maps it accordingly. | `"et-001"` |
| `request_timestamp` | Optional request timestamp. When omitted, the profile can generate the appropriate current timestamp. | `"2026-09-18T18:30:00Z"` |
| `consumer_address` | Optional externally reachable consumer callback URL. | `"https://consumer.example/"` |
| `preview_interval` | Requested ISO-8601 preview interval used by profiles/services that support it. Default: `PT2H`. | `"PT2H"`, `"PT30M"` |
| `initial_termination_time` | Optional initial subscription termination timestamp. | `"2026-09-19T22:00:00Z"` |
| `incremental_updates` | Requests incremental updates where supported. Default: `true`. | `true`, `false` |
| `change_before_updates` | ISO-8601 change-before interval used by profiles/services that support it. Default: `PT30S`. | `"PT30S"`, `"PT1M"` |
| `headers` | Arbitrary HTTP headers added to outbound requests for this subscription. | `{"Authorization": "Bearer ...", "X-Tenant": "dv"}` |
| `logging` | Enables persistent pretty-printed XML communication logging for this subscription. Default: `false`. Logs are not automatically deleted when the subscription is deleted. | `false`, `true` |
| `parameters` | Generic object containing profile-specific parameters. The supported keys and their semantics are documented by each profile. | `{"visId": "VIS-AREA-1"}` |
| `filters.lines` | Optional list of line references used as subscription filters where supported. | `["10", "11"]` |
| `filters.operators` | Optional list of operator references used as subscription filters where supported. | `["OP-1"]` |
| `subscription_policy.update_interval` | Optional ISO-8601 minimum update interval requested from the producer. | `"PT30S"` |
| `heartbeat.enabled` | Requests publisher heartbeat notifications where supported. Default: `true`. | `true`, `false` |
| `heartbeat.interval` | Requested ISO-8601 heartbeat interval. Default: `PT1M`. | `"PT1M"`, `"PT30S"` |
| `heartbeat.timeout_seconds` | Number of seconds without an expected heartbeat before recovery logic may be triggered. Default: `180`. | `180`, `300` |
| `heartbeat.check_status_enabled` | Enables active status checks independently of heartbeat reception. Default: `true`. | `true`, `false` |
| `sink` | Sink configuration used for delivered payloads. Its structure depends on the selected sink type; see [Sinks](sinks.md). | `{"type": "directory", "path": "/data/incoming"}` |

### Complete Create Example

The following example shows a complete request body for creating a standard SIRI subscription. Values are illustrative and should be adapted to the producer and deployment.

```json
{
  "provider_url": "https://producer.example/siri",
  "profile": "default",
  "version": "default",
  "service": "ET",
  "delivery_mode": "direct",
  "requestor_ref": "MY-CONSUMER",
  "subscriber_ref": "MY-SUBSCRIBER",
  "producer_ref": "MY-PRODUCER",
  "subscription_ref": "et-001",
  "request_timestamp": "2026-09-18T18:30:00Z",
  "consumer_address": "https://consumer.example/",
  "preview_interval": "PT2H",
  "initial_termination_time": "2026-09-19T22:00:00Z",
  "incremental_updates": true,
  "change_before_updates": "PT30S",
  "headers": {
    "Authorization": "Bearer example-token",
    "X-Tenant": "dv"
  },
  "logging": true,
  "parameters": {},
  "filters": {
    "lines": [
      "10",
      "11"
    ],
    "operators": [
      "OP-1"
    ]
  },
  "subscription_policy": {
    "update_interval": "PT30S"
  },
  "heartbeat": {
    "enabled": true,
    "interval": "PT1M",
    "timeout_seconds": 180,
    "check_status_enabled": true
  },
  "sink": {
    "type": "http",
    "url": "https://downstream.example/messages",
    "connect_timeout_seconds": 3.0,
    "response_timeout_seconds": 15.0,
    "max_concurrency": 8,
    "headers": {
      "Authorization": "Bearer downstream-token"
    }
  }
}
```

For profile-specific values inside `parameters`, consult the corresponding profile document linked from `docs/profiles.md`. For all supported sink types and their configuration fields, see [Sinks](sinks.md).


## Communication Profile

Every subscription has independent `profile` and `version` fields. Both default to `default`, preserving the existing standard SIRI behavior. A concrete protocol implementation is selected by the `(profile, version)` pair, so incompatible generations such as `de-vdv` version `2` and a future `de-vdv` version `3.1` can coexist. Profile-specific validation happens before a new subscription is persisted. See `docs/profiles.md`.

The `service` field always uses SIRI service codes at the public API boundary, even for non-default profiles. The optional generic `producer_ref` identifies the remote producer where a profile needs an agreed producer identity; `de-vdv` version `2` requires it for callback routing.

## Communication Logging

`logging` is a generic boolean subscription field and defaults to `false`. When enabled, XML request and response payloads associated with the subscription are written to the per-subscription communication log directory. When disabled, the logging component returns before XML parsing and pretty-printing, so disabled subscriptions do not pay that formatting cost.

Deleting a subscription does not delete its communication log directory or files. The application performs no automatic retention or cleanup of these logs. See `docs/communication-logging.md` for filenames, directions, storage configuration, and operational warnings.


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

A successful `DELETE /api/subscriptions/{subscription_ref}` has no durable terminated state. Termination establishes a local delivery cut-off before the publisher termination request is sent. DirectDelivery requests that acquired an inbound delivery lease before that cut-off are allowed to finish, including requests that were already waiting for spool capacity. Requests arriving after the cut-off are rejected with HTTP 410 and cannot create new spool entries. Once the SQLite row is physically deleted, the admission state is marked deleted and later callbacks for that ref return HTTP 404 instead of 410.

After the publisher accepts termination, the consumer waits for all pre-cut-off inbound delivery leases to finish and then drains every accepted spool entry for the subscription through its configured sink. The SQLite row is deleted only after the subscription spool is empty. The cached sink is then closed and removed. No accepted backlog is purged as part of a successful termination. The same `subscription_ref` can subsequently be created again, which reopens inbound delivery admission for that ref.

If publisher termination fails, the subscription remains persisted with status `failed`, inbound delivery admission is reopened, and its spool/sink state is retained so the failure is visible and recoverable.

An operator can explicitly remove such a subscription locally with `DELETE /api/subscriptions/{subscription_ref}?force`. The empty `force` query flag skips the publisher termination request, but preserves the normal local safety guarantees: inbound admission is closed, deliveries admitted before the cut-off are allowed to finish, accepted spool entries are drained through the sink, the SQLite row is deleted, and the cached sink is removed. Communication logs remain untouched. Because the publisher is not contacted, it may still consider the subscription active. Supplying a value such as `?force=true` or `?force=false` does not enable force deletion.

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
