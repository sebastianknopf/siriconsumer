from __future__ import annotations

import asyncio
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.background import BackgroundTasks
from fastapi.responses import FileResponse, Response

COMMUNICATION_LOG_ROOT = Path("/var/log/siri")

router = APIRouter(
    prefix="/api/subscriptions/{subscription_ref}/logs",
    tags=["subscription-logs"],
)


def _log_directory(subscription_ref: str) -> Path:
    return COMMUNICATION_LOG_ROOT / quote(subscription_ref, safe="")


async def _require_subscription(request: Request, subscription_ref: str) -> None:
    record = await request.app.state.services.repository.get(subscription_ref)
    if record is None:
        raise HTTPException(status_code=404, detail="Subscription not found")


def _create_log_archive(subscription_ref: str) -> Path:
    log_directory = _log_directory(subscription_ref)
    handle = tempfile.NamedTemporaryFile(
        prefix="siriconsumer-logs-",
        suffix=".zip",
        delete=False,
    )
    archive_path = Path(handle.name)
    handle.close()

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if log_directory.is_dir():
            for path in sorted(log_directory.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(log_directory))
    return archive_path


def _clear_logs(subscription_ref: str) -> None:
    log_directory = _log_directory(subscription_ref)
    if not log_directory.is_dir():
        return

    for path in log_directory.iterdir():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


@router.get("/download")
async def download_subscription_logs(
    subscription_ref: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> FileResponse:
    await _require_subscription(request, subscription_ref)
    archive_path = await asyncio.to_thread(_create_log_archive, subscription_ref)
    background_tasks.add_task(archive_path.unlink, missing_ok=True)
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=f"{subscription_ref}-logs.zip",
        background=background_tasks,
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_subscription_logs(
    subscription_ref: str,
    request: Request,
) -> Response:
    await _require_subscription(request, subscription_ref)
    await asyncio.to_thread(_clear_logs, subscription_ref)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
