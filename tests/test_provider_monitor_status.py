from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from siriconsumer.domain.models import SubscriptionCreate, SubscriptionRecord
from siriconsumer.services.provider_monitor import ProviderMonitor


@pytest.mark.asyncio
async def test_status_polling_is_per_subscription_and_respects_enabled():
    def record(ref, enabled=True, interval=30):
        config = SubscriptionCreate.model_validate({
            "provider_url": "https://provider.example/siri",
            "service": "VM",
            "delivery_mode": "direct",
            "subscriber_ref": "client",
            "subscription_ref": ref,
            "status": {"enabled": enabled, "interval": f"PT{interval}S"},
            "sink": {"type": "directory", "path": "/tmp/output"},
        })
        return SubscriptionRecord(config=config)

    repository = SimpleNamespace(list_all=AsyncMock(return_value=[
        record("fast", interval=1), record("slow", interval=60),
        record("disabled", enabled=False),
    ]))
    client = SimpleNamespace(check_status=AsyncMock(return_value=SimpleNamespace(
        healthy=True, data_ready=False, service_started_time=None
    )))
    monitor = ProviderMonitor(SimpleNamespace(), repository, client, SimpleNamespace())
    await monitor._check_all_providers()
    assert [call.args[0].config.subscription_ref for call in client.check_status.await_args_list] == [
        "fast", "slow"
    ]
    await monitor._check_all_providers()
    assert client.check_status.await_count == 2
    monitor._next_status_check["fast"] = 0
    await monitor._check_all_providers()
    assert client.check_status.await_count == 3
    assert client.check_status.await_args.args[0].config.subscription_ref == "fast"
