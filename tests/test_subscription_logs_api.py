from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient

import siriconsumer.api.subscription_logs as subscription_logs
from siriconsumer.api.subscription_logs import log_generation, router


class RepositoryStub:
    async def get(self, subscription_ref: str):
        if subscription_ref != "sub-1":
            return None
        return SimpleNamespace(created_at=datetime(2026, 9, 27, 8, 0, tzinfo=timezone.utc))


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(subscription_logs, "COMMUNICATION_LOG_ROOT", tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.state.services = SimpleNamespace(repository=RepositoryStub())
    return TestClient(app)


def test_download_active_subscription_generation(tmp_path, monkeypatch) -> None:
    generation = log_generation(datetime(2026, 9, 27, 8, 0, tzinfo=timezone.utc))
    log_dir = tmp_path / "sub-1" / generation
    log_dir.mkdir(parents=True)
    (log_dir / "message.xml").write_text("<Siri/>")
    response = _client(tmp_path, monkeypatch).get("/api/subscriptions/sub-1/logs/download")
    assert response.status_code == 200
    archive_path = tmp_path / "download.zip"
    archive_path.write_bytes(response.content)
    with ZipFile(archive_path) as archive:
        assert archive.namelist() == ["message.xml"]


def test_deleted_subscription_logs_remain_downloadable(tmp_path, monkeypatch) -> None:
    log_dir = tmp_path / "deleted-sub" / "generation-1"
    log_dir.mkdir(parents=True)
    (log_dir / "message.xml").write_text("<Siri/>")
    response = _client(tmp_path, monkeypatch).get("/api/subscriptions/deleted-sub/logs/download")
    assert response.status_code == 200


def test_archived_generation_can_be_cleared_without_subscription(tmp_path, monkeypatch) -> None:
    log_dir = tmp_path / "deleted-sub" / "generation-1"
    log_dir.mkdir(parents=True)
    (log_dir / "message.xml").write_text("<Siri/>")
    response = _client(tmp_path, monkeypatch).delete(
        "/api/subscriptions/deleted-sub/logs?generation=generation-1"
    )
    assert response.status_code == 204
    assert not log_dir.exists()


def test_unknown_logs_return_404(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.get("/api/subscriptions/missing/logs/download").status_code == 404
    assert client.delete("/api/subscriptions/missing/logs").status_code == 404
