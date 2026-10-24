from __future__ import annotations

from siriconsumer.domain.models import SubscriptionCreate


def test_subscription_model_supports_filters_and_mqtt_sink() -> None:
    model = SubscriptionCreate.model_validate(
        {
            "provider_url": "https://publisher.example/siri",
            "service": "VM",
            "delivery_mode": "direct",

            "subscriber_ref": "consumer",
            "subscription_ref": "sub-1",
            "consumer_address": "https://consumer.example/",
            "headers": {"Authorization": "Bearer secret", "X-Tenant": "tenant-a"},
            "filters": {"lines": ["10"], "operators": ["op-1"]},
            "subscription_policy": {"update_interval": "PT30S"},
            "heartbeat": {
                "enabled": True,
                "interval": "PT45S",
                "timeout_seconds": 180,
            },
            "status": {"enabled": False, "interval": "PT1M"},
            "sink": {
                "type": "mqtt",
                "hostname": "mqtt",
                "topic": "siri/{subscription_ref}",
                "qos": 1,
            },
        }
    )
    assert model.headers == {"Authorization": "Bearer secret", "X-Tenant": "tenant-a"}
    assert model.filters.lines == ["10"]
    assert model.subscription_policy.update_interval == "PT30S"
    assert model.heartbeat.interval == "PT45S"
    assert model.status.enabled is False
    assert model.status.interval == "PT1M"
    assert model.status.interval_seconds == 60
    assert model.sink.type == "mqtt"


def test_mtls_requires_both_certificate_and_key_filenames() -> None:
    base = {
        "provider_url": "https://publisher.example/siri",
        "service": "VM",
        "delivery_mode": "direct",

        "subscriber_ref": "consumer",
        "subscription_ref": "sub-mtls",
        "sink": {"type": "directory", "path": "/tmp/output"},
    }

    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SubscriptionCreate.model_validate({**base, "mtls": {"cert_filename": "/certs/client.crt"}})

    with pytest.raises(ValidationError):
        SubscriptionCreate.model_validate({**base, "mtls": {"key_filename": "/certs/client.key"}})

    with pytest.raises(ValidationError):
        SubscriptionCreate.model_validate(
            {**base, "mtls": {"cert_filename": "", "key_filename": "/certs/client.key"}}
        )


def test_subscription_filters_keep_existing_shape_and_add_vdv31_extensions() -> None:
    model = SubscriptionCreate.model_validate({
        "provider_url": "https://publisher.example/vdv",
        "profile": "de-vdv",
        "version": "3.1",
        "service": "ET",
        "delivery_mode": "fetched",

        "subscriber_ref": "consumer",
        "producer_ref": "producer",
        "subscription_ref": "sub-vdv31",
        "filters": {
            "lines": ["10"],
            "directions": ["A"],
            "operators": ["85:11"],
            "products": ["Bus"],
            "vehicle_modes": ["NFB"],
            "stops": [[{"stop_id": "de:1:stop", "platform_id": "de:1:stop:1"}]],
        },
        "sink": {"type": "directory", "path": "/tmp/output"},
    })
    assert model.filters.lines == ["10"]
    assert model.filters.operators == ["85:11"]
    assert model.filters.directions == ["A"]
    assert model.filters.products == ["Bus"]
    assert model.filters.vehicle_modes == ["NFB"]
    assert model.filters.stops[0][0].stop_id == "de:1:stop"


def test_status_interval_rejects_invalid_and_short_durations() -> None:
    import pytest
    from pydantic import ValidationError
    from siriconsumer.domain.models import StatusConfig

    for interval in ("30", "PT0S", "PT0.5S", "invalid", "-PT1M"):
        with pytest.raises(ValidationError):
            StatusConfig(interval=interval)
    assert StatusConfig(interval="PT2M").interval_seconds == 120
