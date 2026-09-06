from __future__ import annotations

import json

import aiosqlite
import pytest

from siriconsumer.domain.models import MqttSinkConfig, SubscriptionCreate
from siriconsumer.infrastructure.sqlite_repository import SqliteSubscriptionRepository
from siriconsumer.interfaces.intf_subscription_repository import SubscriptionAlreadyExistsError


def _mqtt_config(subscription_ref: str = "sub-secret") -> SubscriptionCreate:
    return SubscriptionCreate.model_validate(
        {
            "provider_url": "https://publisher.example/siri",
            "service": "VM",
            "delivery_mode": "direct",
            "requestor_ref": "consumer",
            "subscriber_ref": "consumer",
            "subscription_ref": subscription_ref,
            "sink": {
                "type": "mqtt",
                "hostname": "mqtt.example.com",
                "username": "mqtt-user",
                "password": "correct horse battery staple",
            },
        }
    )


def test_normal_json_serialization_keeps_mqtt_password_masked() -> None:
    config = _mqtt_config()
    serialized = config.model_dump_json()

    assert "correct horse battery staple" not in serialized
    assert "**********" in serialized


@pytest.mark.asyncio
async def test_sqlite_round_trip_preserves_real_mqtt_password(tmp_path) -> None:
    database_path = tmp_path / "subscriptions.db"
    repository = SqliteSubscriptionRepository(str(database_path))
    await repository.initialize()

    record = await repository.create(_mqtt_config())

    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "SELECT config_json FROM subscriptions WHERE subscription_ref = ?",
            (record.config.subscription_ref,),
        )
        row = await cursor.fetchone()

    assert row is not None
    stored = json.loads(row[0])
    assert stored["sink"]["password"] == "correct horse battery staple"

    loaded = await repository.get(record.config.subscription_ref)
    assert loaded is not None
    assert isinstance(loaded.config.sink, MqttSinkConfig)
    assert loaded.config.sink.password is not None
    assert loaded.config.sink.password.get_secret_value() == "correct horse battery staple"


@pytest.mark.asyncio
async def test_subscription_ref_is_unique_in_sqlite(tmp_path) -> None:
    database_path = tmp_path / "subscriptions.db"
    repository = SqliteSubscriptionRepository(str(database_path))
    await repository.initialize()

    await repository.create(_mqtt_config("same-ref"))

    with pytest.raises(SubscriptionAlreadyExistsError, match="same-ref"):
        await repository.create(_mqtt_config("same-ref"))
