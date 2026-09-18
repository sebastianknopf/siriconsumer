# Sinks

A subscription uses exactly one sink to forward payloads after they have been durably accepted into the local spool.

The `sink` object is a discriminated configuration object. Its `type` property selects the sink implementation and determines which additional properties are valid.

Sink delivery is asynchronous and follows the spool ordering and retry semantics described in [Delivery and Spool](delivery-and-spool.md).

## Directory Sink

The directory sink writes the raw payload to a configured local or mounted directory. Atomic replacement is used so that consumers do not observe partially written files.

| Property | Description | Examples |
| --- | --- | --- |
| `sink.type` | Selects the directory sink. | `"directory"` |
| `sink.path` | Destination directory for delivered payloads. | `"/data/incoming"` |

Example:

```json
{
  "type": "directory",
  "path": "/data/incoming"
}
```

## HTTP Sink

The HTTP sink forwards payloads using asynchronous HTTP requests. Connection and response timeouts are configured independently. A semaphore limits concurrent sends. Failed deliveries remain in the durable spool and are retried according to the normal sink retry policy.

| Property | Description | Examples |
| --- | --- | --- |
| `sink.type` | Selects the HTTP sink. | `"http"` |
| `sink.url` | HTTP target URL receiving the payload. | `"https://downstream.example/messages"` |
| `sink.connect_timeout_seconds` | Maximum connection-establishment time in seconds. Default: `3.0`. | `3.0`, `10.0` |
| `sink.response_timeout_seconds` | Maximum response wait time in seconds. Default: `15.0`. | `15.0`, `30.0` |
| `sink.max_concurrency` | Maximum number of concurrent HTTP sends. Default: `8`; allowed range: 1–128. | `8`, `16` |
| `sink.headers` | Additional HTTP headers sent with each delivery. Default: empty object. | `{"Authorization": "Bearer ..."}` |

Example:

```json
{
  "type": "http",
  "url": "https://downstream.example/messages",
  "connect_timeout_seconds": 3.0,
  "response_timeout_seconds": 15.0,
  "max_concurrency": 8,
  "headers": {
    "Authorization": "Bearer downstream-token"
  }
}
```

## S3 Sink

The S3 sink uploads the raw payload bytes as an object. Credentials are resolved by the AWS SDK credential chain, for example from environment variables, task roles, or instance profiles. `endpoint_url` can be used for an S3-compatible object store.

| Property | Description | Examples |
| --- | --- | --- |
| `sink.type` | Selects the S3 sink. | `"s3"` |
| `sink.bucket` | Destination bucket name. | `"siri-deliveries"` |
| `sink.prefix` | Object-key prefix. Default: `incoming/`. | `"incoming/"`, `"production/siri/"` |
| `sink.region_name` | Optional AWS/S3 region. | `"eu-central-1"` |
| `sink.endpoint_url` | Optional custom S3-compatible endpoint URL. | `"https://s3.example.net"` |

Example:

```json
{
  "type": "s3",
  "bucket": "siri-deliveries",
  "prefix": "incoming/",
  "region_name": "eu-central-1"
}
```

## MQTT Sink

The MQTT sink publishes raw payload bytes to the configured topic. One MQTT client connection is kept per subscription sink and reused for consecutive messages. If connecting or publishing fails, or a timeout expires, the client is discarded and the durable spool retries the same message using a fresh connection.

QoS 1 is the recommended default and provides at-least-once delivery semantics. Downstream consumers should therefore tolerate duplicate messages.

| Property | Description | Examples |
| --- | --- | --- |
| `sink.type` | Selects the MQTT sink. | `"mqtt"` |
| `sink.hostname` | MQTT broker hostname. | `"mqtt.example.net"` |
| `sink.port` | MQTT broker port. Default: `1883`. | `1883`, `8883` |
| `sink.topic` | MQTT topic. `{subscription_ref}` can be used as a template variable. Default: `siri/messages/{subscription_ref}`. | `"siri/messages/{subscription_ref}"` |
| `sink.qos` | MQTT QoS level. Default: `1`. | `0`, `1`, `2` |
| `sink.retain` | MQTT retain flag. Default: `false`. | `false`, `true` |
| `sink.username` | Optional MQTT username. | `"siriconsumer"` |
| `sink.password` | Optional MQTT password. It is treated as a secret by the application model. | `"secret"` |
| `sink.tls` | Enables TLS for the MQTT connection. Default: `false`. | `false`, `true` |
| `sink.connect_timeout_seconds` | Maximum broker connection time in seconds. Default: `10.0`. | `10.0`, `20.0` |
| `sink.publish_timeout_seconds` | Maximum time for one publish operation, including the QoS acknowledgement. Default: `30.0`. | `30.0`, `60.0` |
| `sink.disconnect_timeout_seconds` | Maximum time allowed for best-effort disconnect cleanup. Default: `5.0`. | `5.0`, `10.0` |

Example:

```json
{
  "type": "mqtt",
  "hostname": "mqtt.example.net",
  "port": 8883,
  "topic": "siri/messages/{subscription_ref}",
  "qos": 1,
  "retain": false,
  "username": "siriconsumer",
  "password": "secret",
  "tls": true,
  "connect_timeout_seconds": 10.0,
  "publish_timeout_seconds": 30.0,
  "disconnect_timeout_seconds": 5.0
}
```
