# Control API

Swagger UI is exposed at `/api/swagger`. The raw OpenAPI document is exposed at `/api/swagger/openapi.json`.

## Endpoints

- `POST /api/subscriptions` creates and activates a subscription. `subscription_ref` must be globally unique in the local database; duplicate refs are rejected with HTTP 400.
- `GET /api/subscriptions` lists persisted subscriptions.
- `GET /api/subscriptions/{subscription_ref}` returns one subscription.
- `POST /api/subscriptions/{subscription_ref}/restart` performs terminate-then-subscribe recovery.
- `DELETE /api/subscriptions/{subscription_ref}` closes inbound delivery admission, terminates the publisher subscription, waits for deliveries accepted before the cut-off and their spool backlog to drain through the sink, then deletes the subscription from SQLite and closes its cached sink. The endpoint returns `204 No Content` on success.
- `GET /health/live` is a process liveness endpoint.
- `GET /health/ready` checks local persistence readiness.

- `POST /siri` receives SIRI publisher callbacks. DirectDelivery waits for per-subscription spool capacity for up to `SIRI_DIRECT_DELIVERY_THROTTLE_TIMEOUT_SECONDS`; if capacity remains exhausted, the endpoint returns HTTP 503 so the publisher can retry. While subscription termination is in progress, new DirectDelivery callbacks return HTTP 410 and do not enter the spool. A DirectDelivery callback admitted before termination is allowed to finish and no longer expires on the normal throttle timeout once termination begins. Once the SQLite subscription row has been physically deleted, later callbacks for that ref return HTTP 404. Recreating the same `subscription_ref` reopens delivery admission.

The exact request and response schemas are visible in Swagger UI.
