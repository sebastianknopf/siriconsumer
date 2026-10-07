# SIRI Consumer

`SIRI Consumer` is a self-contained Python 3.12+ service for running and supervising SIRI subscriptions inside a single Docker container. It exposes a REST control API, receives SIRI traffic, restores subscriptions after restarts, durably buffers incoming payloads, and forwards the original payload bytes to pluggable downstream sinks without requiring an external database or queue.

## HTTP Endpoints and Port

The control API and the inbound SIRI endpoint are served by the **same FastAPI application and the same TCP port**. The default container port is `8080`.

## Quickstart

The published Docker image is available as `sebastianknopf/siriconsumer`. Use `latest` for the current `main` build or a release tag such as `1.0.0` for a fixed version.

Create the persistent host directories first:

```bash
mkdir -p state output log/siri
```

The container runs as UID/GID `10001`. If the directories are not writable by that user on the host, adjust their ownership before starting the container.

### Run the Published Docker Image

Pull and run the latest image directly from Docker Hub:

```bash
docker pull sebastianknopf/siriconsumer:latest

docker run --name siriconsumer \
  -p 8080:8080 \
  -v "$(pwd)/state:/app/state" \
  -v "$(pwd)/output:/app/output" \
  -v "$(pwd)/log/siri:/var/log/siri" \
  --restart unless-stopped \
  sebastianknopf/siriconsumer:latest
```

For a fixed release, replace `latest` with a published version such as `1.0.0`.

The same setup is available through `compose.dockerhub.yaml`:

```bash
docker compose -f compose.dockerhub.yaml pull
docker compose -f compose.dockerhub.yaml up -d
```

To run a fixed version with Compose:

```bash
SIRICONSUMER_VERSION=1.0.0 docker compose -f compose.dockerhub.yaml up -d
```

`SIRICONSUMER_VERSION` defaults to `latest`.

### Build Locally from Git

Clone the repository and build the image from the local source tree:

```bash
git clone https://github.com/sebastianknopf/siriconsumer.git
cd siriconsumer
mkdir -p state output log/siri

docker build -t siriconsumer:local .
```

Run the locally built image:

```bash
docker run --name siriconsumer \
  -p 8080:8080 \
  -v "$(pwd)/state:/app/state" \
  -v "$(pwd)/output:/app/output" \
  -v "$(pwd)/log/siri:/var/log/siri" \
  --restart unless-stopped \
  siriconsumer:local
```

Or build and start the local checkout with the standard Compose file:

```bash
docker compose up --build -d
```

In both variants, `/app/state` contains the SQLite subscription state and durable spool, `/app/output` is available to directory sinks, and `/var/log/siri` contains optional per-subscription communication logs. The Compose files mount these paths to `./state`, `./output`, and `./log/siri`.

After startup, open the Swagger UI at:

```text
http://localhost:8080/api/swagger
```

The runtime status overview is available at `http://localhost:8080/status`. It shows consumer health and per-subscription lifecycle, heartbeat, last-message, and payload-only spool information.



Communication XML logging is disabled by default and can be enabled per subscription with `"logging": true`. Logged XML is written below `/var/log/siri/{subscription_ref}/`. The files deliberately survive subscription deletion and are never cleaned up automatically by the application. See [`docs/communication-logging.md`](docs/communication-logging.md).

## Docker Image Publishing

Two GitHub Actions publish `sebastianknopf/siriconsumer` to Docker Hub:

- `.github/workflows/docker-latest.yml` runs whenever `main` is updated, including after a pull request is merged, and publishes `sebastianknopf/siriconsumer:latest`.
- `.github/workflows/docker-release.yml` runs for pushed `1.x.x` Git tags and publishes the exact tag, for example `sebastianknopf/siriconsumer:1.2.3`.

Configure a Docker Hub access token as the GitHub repository secret `DOCKERHUB_TOKEN`. The workflows authenticate as the Docker Hub user `sebastianknopf`.

To publish a versioned image, create and push a matching Git tag:

```bash
git tag 1.0.0
git push origin 1.0.0
```

The Docker build keeps the Git metadata available because the Python package version is derived from Git tags through `setuptools_scm`.

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
  "producer_ref": "producer-a",
  "subscription_ref": "vm-example",
  "consumer_address": "http://siriconsumer:8080/",
  "initial_termination_time": "2999-12-31T23:59:59Z",
  "incremental_updates": true,
  "sink": {
    "type": "directory",
    "path": "/app/output"
  }
}
```

See a full example for the subscription API in [docs/subscriptions.md][docs/subscriptions.md].

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

The `de-vdv` profile supports version `2` (VDV 453 2.6.1 / VDV 454 2.2.1, common V2017e schema) and version `3.1` (VDV 453/454 3.1.0, common `VDV453_incl_454_V3.1.0_v12` schema). Subscriptions can carry generic `parameters` and `filters` interpreted by the selected profile. Both VDV versions use fetched delivery and action-specific publisher URLs such as `aboverwalten.xml`, `status.xml`, and `datenabrufen.xml`. The public API always uses SIRI service codes; profiles map them internally. VDV callbacks use the standard `/{producer_ref}/{VDV-service}/{action}.xml` shape. The consumer resolves the matching subscriptions by producer/service and loads the persisted profile/version; multiple subscriptions may share an endpoint, but the endpoint cannot mix VDV profile versions. See [`docs/profiles.md`](docs/profiles.md) for the profile routing model and links to the individual profile documentation.

## License

This project is licensed under the Apache 2.0 license. See [LICENSE.md](LICENSE.md) for more information.
