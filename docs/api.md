# Control API

Swagger UI is exposed at `/api/swagger`. The raw OpenAPI document is exposed at `/api/swagger/openapi.json`.

## Endpoints

- `POST /api/subscriptions` creates and activates a subscription.
- `GET /api/subscriptions` lists persisted subscriptions.
- `GET /api/subscriptions/{subscription_id}` returns one subscription.
- `POST /api/subscriptions/{subscription_id}/restart` performs terminate-then-subscribe recovery.
- `DELETE /api/subscriptions/{subscription_id}` terminates and marks a subscription terminated.
- `GET /health/live` is a process liveness endpoint.
- `GET /health/ready` checks local persistence readiness.

- `POST /siri` receives SIRI publisher callbacks.

The exact request and response schemas are visible in Swagger UI.
