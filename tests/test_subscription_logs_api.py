from __future__ import annotations

from types import SimpleNamespace
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient

import siriconsumer.api.subscription_logs as subscription_logs
from siriconsumer.api.subscription_logs import router


class RepositoryStub:
    async def get(self, subscription_ref: str):
        return object() if subscription_ref == "sub-1" else None


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(subscription_logs, "COMMUNICATION_LOG_ROOT", tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.state.services = SimpleNamespace(repository=RepositoryStub())
    return TestClient(app)


def test_download_subscription_logs_returns_zip(tmp_path, monkeypatch) -> None:
    log_dir = tmp_path / "sub-1"
    log_dir.mkdir()
    (log_dir / "message.xml").write_text("<Siri/>")
    response = _client(tmp_path, monkeypatch).get("/api/subscriptions/sub-1/logs/download")
    assert response.status_code == 200
    archive_path = tmp_path / "download.zip"
    archive_path.write_bytes(response.content)
    with ZipFile(archive_path) as archive:
        assert archive.namelist() == ["message.xml"]
        assert archive.read("message.xml") == b"<Siri/>"


def test_clear_subscription_logs_removes_files_but_keeps_directory(tmp_path, monkeypatch) -> None:
    log_dir = tmp_path / "sub-1"
    log_dir.mkdir()
    (log_dir / "message.xml").write_text("<Siri/>")
    response = _client(tmp_path, monkeypatch).delete("/api/subscriptions/sub-1/logs")
    assert response.status_code == 204
    assert log_dir.is_dir()
    assert list(log_dir.iterdir()) == []


def test_log_endpoints_return_404_for_unknown_subscription(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.get("/api/subscriptions/missing/logs/download").status_code == 404
    assert client.delete("/api/subscriptions/missing/logs").status_code == 404
