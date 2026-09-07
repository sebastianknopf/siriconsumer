# Control API

Swagger UI is exposed at `/api/swagger`. The raw OpenAPI document is exposed at `/api/swagger/openapi.json`.

## Endpoints

- `POST /api/subscriptions` creates and activates a subscription. `subscription_ref` must be globally unique in the local database; duplicate refs are rejected with HTTP 400.
- `GET /api/subscriptions` lists persisted subscriptions.
- `GET /api/subscriptions/{subscription_ref}` returns one subscription.
- `POST /api/subscriptions/{subscription_ref}/restart` performs terminate-then-subscribe recovery.
- `DELETE /api/subscriptions/{subscription_ref}` terminates the publisher subscription, deletes it from SQLite, purges its spool entries, and closes its cached sink. The endpoint returns `204 No Content` on success.
- `GET /health/live` is a process liveness endpoint.
- `GET /health/ready` checks local persistence readiness.

- `POST /siri` receives SIRI publisher callbacks. DirectDelivery waits for per-subscription spool capacity for up to `SIRI_DIRECT_DELIVERY_THROTTLE_TIMEOUT_SECONDS`; if capacity remains exhausted, the endpoint returns HTTP 503 so the publisher can retry.

The exact request and response schemas are visible in Swagger UI.
