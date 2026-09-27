from __future__ import annotations

import os

from siriconsumer.services.log_retention import cleanup_communication_logs


def test_cleanup_removes_expired_files(tmp_path) -> None:
    old_file = tmp_path / "sub" / "generation" / "old.xml"
    new_file = tmp_path / "sub" / "generation" / "new.xml"
    old_file.parent.mkdir(parents=True)
    old_file.write_bytes(b"old")
    new_file.write_bytes(b"new")
    os.utime(old_file, (100, 100))
    os.utime(new_file, (10000, 10000))

    deleted_files, deleted_bytes = cleanup_communication_logs(
        tmp_path, retention_hours=1, max_size_bytes=0, now=10000
    )

    assert (deleted_files, deleted_bytes) == (1, 3)
    assert not old_file.exists()
    assert new_file.exists()


def test_cleanup_enforces_global_size_cap_oldest_first(tmp_path) -> None:
    first = tmp_path / "a" / "g" / "first.xml"
    second = tmp_path / "b" / "g" / "second.xml"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"12345")
    second.write_bytes(b"67890")
    os.utime(first, (100, 100))
    os.utime(second, (200, 200))

    cleanup_communication_logs(tmp_path, retention_hours=0, max_size_bytes=5, now=10000)

    assert not first.exists()
    assert second.exists()
