from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import BACKUP_DIR, BACKUP_RETENTION_DAYS
from . import db_restore

logger = logging.getLogger(__name__)

BACKUP_FILENAME_PREFIX = "opos-backup-"
BACKUP_FILENAME_SUFFIX = ".db"
_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"


class BackupError(Exception):
    """Raised when a backup operation fails."""


def _resolve_backup_dir(target_dir: Path | None = None) -> Path:
    directory = target_dir or BACKUP_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _format_timestamp(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    return moment.strftime(_TIMESTAMP_FORMAT)


def create_backup(target_dir: Path | None = None) -> Path:
    """Create a single-file SQLite backup using VACUUM INTO.

    VACUUM INTO produces a consistent snapshot even with an active WAL,
    and avoids the need to copy the -wal/-shm sidecar files.
    """

    db_path = db_restore.resolve_sqlite_path()
    if not db_path.exists():
        raise BackupError("Plik bazy danych nie został znaleziony.")

    directory = _resolve_backup_dir(target_dir)
    filename = f"{BACKUP_FILENAME_PREFIX}{_format_timestamp()}{BACKUP_FILENAME_SUFFIX}"
    target_path = directory / filename

    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("VACUUM INTO ?", (str(target_path),))
    except sqlite3.Error as exc:
        target_path.unlink(missing_ok=True)
        raise BackupError("Nie udało się utworzyć kopii zapasowej bazy danych.") from exc

    return target_path


def list_backups(target_dir: Path | None = None) -> list[Path]:
    directory = target_dir or BACKUP_DIR
    if not directory.exists():
        return []
    backups = [
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.name.startswith(BACKUP_FILENAME_PREFIX)
        and path.suffix == BACKUP_FILENAME_SUFFIX
    ]
    backups.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return backups


def delete_old_backups(
    retention_days: int | None = None, target_dir: Path | None = None
) -> int:
    days = BACKUP_RETENTION_DAYS if retention_days is None else retention_days
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    removed = 0
    for path in list_backups(target_dir):
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            try:
                path.unlink()
                removed += 1
            except OSError:
                logger.warning("Nie udało się usunąć starego backupu %s", path)
    return removed


def restore_from_path(source: Path) -> Path:
    """Restore the live database from a backup file on disk.

    Uses the same atomic-replace logic as the upload-based restore, by
    streaming the file through ``db_restore`` validation and replacement.
    """

    if not source.exists():
        raise BackupError(f"Plik kopii zapasowej nie istnieje: {source}")

    target_path = db_restore.resolve_sqlite_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(
        dir=str(target_path.parent), suffix=target_path.suffix or ".db"
    )
    os.close(fd)
    temp_path = Path(temp_name)

    try:
        shutil.copyfile(source, temp_path)
        db_restore._validate_sqlite_file(temp_path)
        db_restore._upgrade_sqlite_file(temp_path)
        db_restore._validate_sqlite_file(temp_path)
        db_restore._replace_sqlite_db(temp_path, target_path)
    except db_restore.DBRestoreError:
        temp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:  # pragma: no cover - guard
        temp_path.unlink(missing_ok=True)
        raise BackupError("Nie udało się przywrócić bazy z kopii zapasowej.") from exc

    temp_path.unlink(missing_ok=True)
    return target_path
