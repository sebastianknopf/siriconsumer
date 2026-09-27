from __future__ import annotations

import logging
import multiprocessing
import time
from pathlib import Path

logger = logging.getLogger(__name__)

COMMUNICATION_LOG_ROOT = Path("/var/log/siri")


def cleanup_communication_logs(
    root: Path,
    *,
    retention_hours: float,
    max_size_bytes: int,
    now: float | None = None,
) -> tuple[int, int]:
    """Delete expired logs and enforce an optional global size cap."""
    if not root.is_dir():
        return 0, 0

    current_time = time.time() if now is None else now
    cutoff = current_time - (retention_hours * 3600) if retention_hours > 0 else None
    files: list[tuple[Path, float, int]] = []
    deleted_files = 0
    deleted_bytes = 0

    for path in root.rglob("*.xml"):
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        
        if cutoff is not None and stat.st_mtime < cutoff:
            try:
                path.unlink()
                deleted_files += 1
                deleted_bytes += stat.st_size
            except FileNotFoundError:
                pass
            continue
        
        files.append((path, stat.st_mtime, stat.st_size))

    if max_size_bytes > 0:
        total_size = sum(size for _, _, size in files)
        for path, _, size in sorted(files, key=lambda item: item[1]):
            if total_size <= max_size_bytes:
                break
            
            try:
                path.unlink()
                total_size -= size
                deleted_files += 1
                deleted_bytes += size
            except FileNotFoundError:
                pass

    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    
    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            pass

    return deleted_files, deleted_bytes


def _retention_worker(
    root: str,
    retention_hours: float,
    check_interval_seconds: float,
    max_size_bytes: int,
    stop_event: multiprocessing.synchronize.Event,
) -> None:
    logging.basicConfig(level=logging.INFO)
    log_root = Path(root)
    while not stop_event.is_set():
        try:
            deleted_files, deleted_bytes = cleanup_communication_logs(
                log_root,
                retention_hours=retention_hours,
                max_size_bytes=max_size_bytes,
            )
            if deleted_files:
                logger.info(
                    "Communication log retention deleted %d files (%d bytes)",
                    deleted_files,
                    deleted_bytes,
                )
        except Exception:
            logger.exception("Communication log retention cleanup failed")
        
        stop_event.wait(check_interval_seconds)


class LogRetentionProcess:
    """Run communication-log retention in a dedicated OS process."""

    def __init__(
        self,
        *,
        root: Path = COMMUNICATION_LOG_ROOT,
        retention_hours: float,
        check_interval_seconds: float,
        max_size_bytes: int,
    ) -> None:
        self._root = root
        self._retention_hours = retention_hours
        self._check_interval_seconds = check_interval_seconds
        self._max_size_bytes = max_size_bytes
        self._context = multiprocessing.get_context("spawn")
        self._stop_event = self._context.Event()
        self._process: multiprocessing.Process | None = None

    def start(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        self._stop_event.clear()
        self._process = self._context.Process(
            target=_retention_worker,
            name="siriconsumer-log-retention",
            args=(
                str(self._root),
                self._retention_hours,
                self._check_interval_seconds,
                self._max_size_bytes,
                self._stop_event,
            ),
            daemon=True,
        )

        self._process.start()

    def stop(self) -> None:
        if self._process is None:
            return
        
        self._stop_event.set()
        self._process.join(timeout=5)
        
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=5)
        
        self._process = None
