## Status page

`GET /status` serves a lightweight Material Design-inspired HTML overview of the running consumer and all persisted subscriptions. The subscription table shows the subscription ID, profile, version, configured termination time, lifecycle status, last data receipt, last heartbeat, and current spool size and data-file count.

The displayed spool value is formatted as `[payload size] / [data-file count]`. Both values refer only to actual `.payload` files currently belonging to the subscription; spool metadata files are deliberately excluded. The page refreshes only when the operator uses the Refresh button and does not require external UI assets.

# Control API

Swagger UI is exposed at `/api/swagger`. The raw OpenAPI document is exposed at `/api/swagger/openapi.json`.

## Endpoints

- `POST /api/subscriptions` creates and activates a subscription. The optional `logging` flag defaults to `false`; when enabled, XML requests and responses for that subscription are persisted as described in `communication-logging.md`. The optional `parameters` object carries profile-specific values and defaults to `{}`. `subscription_ref` must be globally unique in the local database; duplicate refs are rejected with HTTP 400.
- `GET /api/subscriptions` lists persisted subscriptions.
- `GET /api/profiles` lists registered communication profiles, their specification target, supported service codes, and the profile-specific `parameters` keys supported per service.
- `GET /api/subscriptions/{subscription_ref}` returns one subscription.
- `POST /api/subscriptions/{subscription_ref}/restart` performs terminate-then-subscribe recovery.
- `DELETE /api/subscriptions/{subscription_ref}` closes inbound delivery admission, terminates the publisher subscription, waits for deliveries accepted before the cut-off and their spool backlog to drain through the sink, then deletes the subscription from SQLite and closes its cached sink. The endpoint returns `204 No Content` on success. The optional `spool` query parameter defaults to `true`. With `spool=false`, deliveries admitted before the cut-off are still allowed to finish entering the spool, pending spool entries are then discarded, and an entry already being processed by a sink worker is allowed to finish before deletion continues. This behavior is independent of the sink type and of `force`. With `DELETE /api/subscriptions/{subscription_ref}?force`, the consumer still sends the profile-specific publisher termination request, but ignores any failure or negative/unexpected termination response and continues with local termination. The empty `force` query flag must be supplied without a value; `?force=true` and `?force=false` do not enable force deletion. The status page invokes force termination with `?force&spool=false`.
- `GET /health/live` is a process liveness endpoint.
- `GET /health/ready` checks local persistence readiness.

- `POST /` receives callbacks for the `default` SIRI profile.
- `POST /profile/{profileId}/{version}/{path...}` receives callbacks for an explicitly selected profile/version pair. For `de-vdv` versions `2` and `3.1`, paths follow `{producer_ref}/{VDV-service}/{action}.xml`, for example `PRODUCER-LEIPZIG/AUS/datenbereit.xml`. The VDV service is mapped to the SIRI service code used by the subscription API.

`POST /` receives SIRI publisher callbacks. DirectDelivery waits for per-subscription spool capacity for up to `SIRI_DIRECT_DELIVERY_THROTTLE_TIMEOUT_SECONDS`; if capacity remains exhausted, the endpoint returns HTTP 503 so the publisher can retry. While subscription termination is in progress, new DirectDelivery callbacks return HTTP 410 and do not enter the spool. A DirectDelivery callback admitted before termination is allowed to finish and no longer expires on the normal throttle timeout once termination begins. Once the SQLite subscription row has been physically deleted, later callbacks for that ref return HTTP 404. Recreating the same `subscription_ref` reopens delivery admission.

The exact request and response schemas are visible in Swagger UI.

### Subscription Communication Logs

The status page exposes log actions for each subscription:

- `GET /api/subscriptions/{subscription_ref}/logs/download` downloads all currently stored communication logs for the subscription as a ZIP archive.
- `DELETE /api/subscriptions/{subscription_ref}/logs` clears all currently stored communication logs for the subscription.

The log endpoints remain available after a subscription is deleted as long as communication logs still exist. Archived generation-specific actions use the optional `generation` query parameter. Log files are read from the fixed communication log root `/var/log/siri`. Clearing logs does not change a live subscription's `logging` configuration and does not affect subscription state.
