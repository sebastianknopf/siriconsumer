# SIRI Consumer

`SIRI Consumer` is a self-contained Python 3.12+ service for running and supervising SIRI subscriptions inside a single Docker container. It exposes a REST control API, receives SIRI traffic, restores subscriptions after restarts, durably buffers incoming payloads, and forwards the original payload bytes to pluggable downstream sinks without requiring an external database or queue.

## P

- REST API for creating, listing, restarting, and terminating SIRI subscriptions.
- Direct Delivery and Fetched Delivery handling.
- Incoming heartbeat handling plus optional active publisher status checks.
- Publisher restart detection using `ServiceStartedTime` when available.
- Deterministic subscription recovery: terminate first, then recreate from persisted configuration.
- Optional line and operator filters, `ConsumerAddress`, and minimum update interval support where accepted by the selected SIRI service/provider.
- SQLite-backed local subscription state.
- Durable local spool with a maximum of 100 pending messages per subscription by default.
- O(1) oldest-message eviction through an in-memory per-subscription deque; the spool filesystem is scanned only during startup reconstruction.
- Directory, HTTP, S3, and MQTT sinks.
- Preservation of the original inbound payload bytes without XML re-serialization.
- OpenAPI documentation and Swagger UI built into the same service.

## HTTP Endpoints and Port

The control API and the inbound SIRI endpoint are served by the **same FastAPI application and the same port**. The default container port is `8080`.

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

The generated `__version__` is also used as the FastAPI/OpenAPI application version.

## Example Subscription

```json
{
  "provider_url": "https://publisher.example/siri",
  "service": "VM",
  "delivery_mode": "direct",
  "requestor_ref": "consumer-a",
  "subscriber_ref": "consumer-a",
  "subscription_ref": "vm-example",
  "consumer_address": "http://siriconsumer:8080/siri",
  "filters": {
    "lines": ["10", "20"],
    "operators": ["operator-a"]
  },
  "subscription_policy": {
    "update_interval": "PT30S"
  },
  "heartbeat": {
    "enabled": true,
    "timeout_seconds": 180
  },
  "sink": {
    "type": "directory",
    "path": "/app/output"
  }
}
```

## Persistence and Recovery

Subscription configuration is stored in `/app/state/siri.db`. Pending messages are stored under `/app/state/spool`. Mount `/app/state` if subscriptions and pending deliveries must survive container replacement.

At startup, each persisted non-terminated subscription is recovered using the same policy used after a detected publisher restart:

1. Attempt to terminate the previous subscription.
2. Treat an unknown or already-gone subscription as non-fatal.
3. Recreate the subscription from the persisted configuration.
4. Mark it active only after a successful provider response.

See [`docs/architecture.md`](docs/architecture.md), [`docs/subscriptions.md`](docs/subscriptions.md), and [`docs/delivery-and-spool.md`](docs/delivery-and-spool.md) for details.

## Important Interoperability Note

SIRI deployments differ in supported services, request variants, authentication, and optional fields. The XML builder in this project provides a compact generic baseline. Provider-specific profiles or exact XSD-driven request builders can be added behind `intf_siri_client.py` without changing the API, lifecycle manager, spool, or sink implementations.

## License

This project is licensed under the Apache 2.0 license. See [LICENSE.md](LICENSE.md) for more information.
