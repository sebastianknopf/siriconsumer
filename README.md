# SIRI Consumer

`SIRI Consumer` is a self-contained Python 3.12+ service for running and supervising SIRI subscriptions inside a single Docker container. It exposes a REST control API, receives SIRI traffic, restores subscriptions after restarts, durably buffers incoming payloads, and forwards the original payload bytes to pluggable downstream sinks without requiring an external database or queue.

## HTTP Endpoints and Port

The control API and the inbound SIRI endpoint are served by the **same FastAPI application and the same TCP port**. The default container port is `8080`.

## Start with Docker

Build the image:

```bash
docker build -t siriconsumer .
```

Run it:

```bash
docker run --rm \
  -p 8080:8080 \
  -v "$(pwd)/state:/app/state" \
  -v "$(pwd)/output:/app/output" \
  -v "$(pwd)/log/siri:/var/log/siri" \
  siriconsumer
```

The state volume is strongly recommended for production because it contains the SQLite subscription state and the durable delivery spool. The output volume is only required when using the directory sink.

Or use Compose:

```bash
docker compose up --build
```

Then open the Swagger UI:

```text
http://localhost:8080/api/swagger
```

Communication XML logging is disabled by default and can be enabled per subscription with `"logging": true`. Logged XML is written below `/var/log/siri/{subscription_ref}/`; Compose mounts this to `./log/siri` by default. The log files are deliberately retained when a subscription is deleted and are never cleaned up automatically by the application. See [`docs/communication-logging.md`](docs/communication-logging.md).

## Local Development

```bash
python3.12 -m venv .venv
source .venv/bin/activate

pip install -e '.[dev]'
uvicorn siriconsumer.main:app --reload --port 8080
```

Run tests and static checks:

```bash
pytest
ruff check .
mypy src/siriconsumer
```

## Versioning

The project uses `setuptools_scm`. Package versions are derived from Git metadata during build/install, and `setuptools_scm` generates:

```text
src/siriconsumer/version.py
```

## Example Subscription

```json
{
  "provider_url": "https://publisher.example/siri",
  "profile": "default",
  "version": "default",
  "service": "VM",
  "delivery_mode": "direct",
  "requestor_ref": "consumer-a",
  "subscriber_ref": "consumer-a",
  "subscription_ref": "vm-example",
  "logging": false,
  "request_timestamp": "2026-09-08T06:00:00Z",
  "consumer_address": "http://siriconsumer:8080/consumer",
  "preview_interval": "PT2H",
  "initial_termination_time": "2999-12-31T23:59:59Z",
  "incremental_updates": true,
  "change_before_updates": "PT30S",
  "filters": {
    "lines": ["10", "20"],
    "operators": ["operator-a"]
  },
  "subscription_policy": {
    "update_interval": "PT30S"
  },
  "heartbeat": {
    "enabled": true,
    "interval": "PT1M",
    "timeout_seconds": 180,
    "check_status_enabled": false
  },
  "sink": {
    "type": "directory",
    "path": "/app/output"
  }
}
```

## Persistence and Recovery

`subscription_ref` is the single subscription identifier throughout the application and must be unique in the local database. Creating a second subscription with the same ref returns HTTP 400.

Subscription configuration is stored in `/app/state/siri.db`. Pending messages are stored under `/app/state/spool`. Mount `/app/state` if subscriptions and pending deliveries must survive container replacement.

At startup, each persisted subscription is recovered using the same policy used after a detected publisher restart:

1. Attempt to terminate the previous subscription.
2. Treat an unknown or already-gone subscription as non-fatal.
3. Recreate the subscription from the persisted configuration.
4. Mark it active only after a successful provider response.

See [`docs/architecture.md`](docs/architecture.md), [`docs/subscriptions.md`](docs/subscriptions.md), [`docs/profiles.md`](docs/profiles.md), and [`docs/delivery-and-spool.md`](docs/delivery-and-spool.md) for details.

## Delivery Backpressure and FetchedDelivery Limits

The spool never evicts an older accepted message to admit a newer one. DirectDelivery waits for spool capacity and returns HTTP 503 only when `SIRI_DIRECT_DELIVERY_THROTTLE_TIMEOUT_SECONDS` expires. FetchedDelivery follows `MoreData=true` with additional `DataSupplyRequest` calls, bounded by `SIRI_FETCHED_DELIVERY_MAX_MORE_DATA_REQUESTS`. See `docs/delivery-and-spool.md` for the exact semantics.

## Communication Profiles

Subscriptions use the `default` profile unless `profile` is explicitly set. The default profile preserves the existing standard SIRI behavior and `/consumer` callback endpoint. Versioned profiles can provide different XML dialects, URL rules, and inbound callback semantics without changing the spool or sink pipeline.

The first additional profile is `de-vdv` version `2`, targeting VDV 453 2.6.1 and VDV 454 2.2.1 with the common V2017e schema generation. Subscriptions can carry a generic `parameters` object whose keys are interpreted only by the selected profile. It uses VDV fetched delivery and action-specific publisher URLs such as `aboverwalten.xml`, `status.xml`, and `datenabrufen.xml`. The public API always uses SIRI service codes; profiles map them internally. VDV callbacks are routed as `/consumer/profile/de-vdv/2/{producer_ref}/{VDV-service}/{action}.xml`. See [`docs/profiles.md`](docs/profiles.md) for the profile routing model and links to the individual profile documentation.

## License

This project is licensed under the Apache 2.0 license. See [LICENSE.md](LICENSE.md) for more information.
