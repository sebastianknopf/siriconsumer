from __future__ import annotations

from siriconsumer.domain.models import SubscriptionCreate


def test_subscription_model_supports_filters_and_mqtt_sink() -> None:
    model = SubscriptionCreate.model_validate(
        {
            "provider_url": "https://publisher.example/siri",
            "service": "VM",
            "delivery_mode": "direct",
            "requestor_ref": "consumer",
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
                "check_status_enabled": False,
            },
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
    assert model.heartbeat.check_status_enabled is False
    assert model.sink.type == "mqtt"


def test_mtls_requires_both_certificate_and_key_filenames() -> None:
    base = {
        "provider_url": "https://publisher.example/siri",
        "service": "VM",
        "delivery_mode": "direct",
        "requestor_ref": "consumer",
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
