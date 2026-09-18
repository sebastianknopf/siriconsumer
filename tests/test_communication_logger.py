from pathlib import Path

import pytest

from siriconsumer.domain.enums import DeliveryMode
from siriconsumer.domain.models import DirectorySinkConfig, SubscriptionCreate, SubscriptionRecord
import siriconsumer.services.communication_logger as communication_logger_module
from siriconsumer.services.communication_logger import FileCommunicationLogger


def _subscription(*, logging: bool) -> SubscriptionRecord:
    return SubscriptionRecord(
        config=SubscriptionCreate(
            provider_url="https://producer.example/siri",
            service="VM",
            delivery_mode=DeliveryMode.DIRECT,
            requestor_ref="consumer",
            subscriber_ref="consumer",
            subscription_ref="vm/test",
            logging=logging,
            sink=DirectorySinkConfig(path=Path("/tmp/output")),
        )
    )


@pytest.mark.asyncio
async def test_disabled_logging_does_not_parse_xml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(communication_logger_module, "COMMUNICATION_LOG_ROOT", tmp_path)
    logger = FileCommunicationLogger()
    await logger.write(
        _subscription(logging=False),
        direction="IN",
        kind="Request",
        payload=b"this is deliberately not XML",
    )

    assert list(tmp_path.rglob("*")) == []


@pytest.mark.asyncio
async def test_enabled_logging_writes_pretty_xml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(communication_logger_module, "COMMUNICATION_LOG_ROOT", tmp_path)
    logger = FileCommunicationLogger()
    await logger.write(
        _subscription(logging=True),
        direction="OUT",
        kind="Response",
        payload=b"<root><value>1</value></root>",
    )

    files = list((tmp_path / "vm%2Ftest").glob("*_OUT_Response.xml"))
    assert len(files) == 1
    assert files[0].name[:23].count("-") == 6
    assert files[0].read_bytes() == (
        b'<?xml version=\'1.0\' encoding=\'UTF-8\'?>\n'
        b"<root>\n  <value>1</value>\n</root>\n"
    )
