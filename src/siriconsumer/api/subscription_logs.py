from __future__ import annotations

import asyncio
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.background import BackgroundTasks
from fastapi.responses import FileResponse, Response

COMMUNICATION_LOG_ROOT = Path("/var/log/siri")

router = APIRouter(
    prefix="/api/subscriptions/{subscription_ref}/logs",
    tags=["subscription-logs"],
)


def log_directory(subscription_ref: str) -> Path:
    return COMMUNICATION_LOG_ROOT / quote(subscription_ref, safe="")


def log_generation(created_at: datetime) -> str:
    return created_at.astimezone().strftime("%Y%m%dT%H%M%S%f%z")


def _validate_generation(generation: str) -> str:
    if not generation or generation in {".", ".."} or "/" in generation or "\\" in generation:
        raise HTTPException(status_code=400, detail="Invalid log generation")
    return generation


async def _resolve_log_path(
    request: Request,
    subscription_ref: str,
    generation: str | None,
) -> Path:
    base = log_directory(subscription_ref)
    if generation is not None:
        return base / _validate_generation(generation)

    record = await request.app.state.services.repository.get(subscription_ref)
    if record is not None:
        current = base / log_generation(record.created_at)
        if current.exists():
            return current
        # Compatibility with logs written before generation directories existed.
        if any(path.is_file() for path in base.glob("*.xml")):
            return base
        return current

    if not base.exists():
        raise HTTPException(status_code=404, detail="Communication logs not found")
    return base


def _create_log_archive(log_path: Path) -> Path:
    handle = tempfile.NamedTemporaryFile(prefix="siriconsumer-logs-", suffix=".zip", delete=False)
    archive_path = Path(handle.name)
    handle.close()
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if log_path.is_dir():
            for path in sorted(log_path.rglob("*.xml")):
                if path.is_file():
                    archive.write(path, path.relative_to(log_path))
    
    return archive_path


def _clear_logs(log_path: Path) -> None:
    if not log_path.is_dir():
        return
    for path in list(log_path.iterdir()):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    
    try:
        log_path.rmdir()
    except OSError:
        pass


@router.get("/download")
async def download_subscription_logs(
    subscription_ref: str,
    request: Request,
    background_tasks: BackgroundTasks,
    generation: str | None = Query(default=None),
) -> FileResponse:
    log_path = await _resolve_log_path(request, subscription_ref, generation)
    if not log_path.is_dir():
        raise HTTPException(status_code=404, detail="Communication logs not found")
    
    archive_path = await asyncio.to_thread(_create_log_archive, log_path)
    background_tasks.add_task(archive_path.unlink, missing_ok=True)
    
    suffix = f"-{generation}" if generation else ""
    
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=f"{subscription_ref}{suffix}-logs.zip",
        background=background_tasks,
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_subscription_logs(
    subscription_ref: str,
    request: Request,
    generation: str | None = Query(default=None),
) -> Response:
    log_path = await _resolve_log_path(request, subscription_ref, generation)
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Communication logs not found")
    
    await asyncio.to_thread(_clear_logs, log_path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
