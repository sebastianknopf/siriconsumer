# Subscription Lifecycle

## States

The implementation uses the following high-level states:

- `creating`
- `active`
- `degraded`
- `terminating`
- `terminated`
- `failed`

## Recovery Policy

Recovery is intentionally deterministic. The consumer does not trust that a previously active publisher-side subscription still exists after either side restarts.

For every subscription that must be recovered:

1. Send a termination request using the stored subscription references.
2. Ignore an "unknown subscription" result as a successful cleanup condition.
3. Send a fresh subscription request using the same stored configuration.
4. Persist the active state only after a successful response.

The same procedure is used for:

- Consumer startup.
- Manual `POST /api/subscriptions/{id}/restart`.
- Publisher restart detection.
- Heartbeat/status monitoring that concludes the subscription must be recreated.

## Publisher Restart Detection

When available, `ServiceStartedTime` is treated as a publisher-instance marker. It may be learned from inbound heartbeat/status messages or active `CheckStatus` responses. A change from the last persisted value indicates a publisher restart and triggers recovery of all subscriptions using that provider URL.

If a publisher does not provide `ServiceStartedTime`, heartbeat timeout or active health-check failure can mark subscriptions degraded, but that signal is inherently less precise than an explicit start-time change.

## Filters

The public model supports optional `lines` and `operators` lists from the start. The generic XML builder maps them into service request structures where practical. Real SIRI deployments differ, so provider/service-specific builders can validate or override this mapping behind the SIRI client interface.

## Consumer Address

`consumer_address` is optional. If omitted, the configured provider may infer or preconfigure the callback endpoint. For direct delivery, deployments commonly need a callback address that is reachable from the publisher.

## Update Interval

`subscription_policy.update_interval` accepts an ISO-8601 duration such as `PT30S`. It represents the requested minimum interval between publisher updates where the selected SIRI service and publisher support such a field. It is not a local rate limiter and cannot force a non-compliant publisher to wait.
