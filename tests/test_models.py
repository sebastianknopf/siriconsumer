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
            "consumer_address": "https://consumer.example/siri",
            "filters": {"lines": ["10"], "operators": ["op-1"]},
            "subscription_policy": {"update_interval": "PT30S"},
            "sink": {
                "type": "mqtt",
                "hostname": "mqtt",
                "topic": "siri/{subscription_ref}",
                "qos": 1,
            },
        }
    )
    
    assert model.filters.lines == ["10"]
    assert model.subscription_policy.update_interval == "PT30S"
    assert model.sink.type == "mqtt"
