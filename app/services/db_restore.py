from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import close_all_sessions

from ..config import DATA_DIR, DB_URL
from ..db import SessionLocal, engine

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REQUIRED_TABLES = {
    "users",
    "armies",
    "unit_templates",
    "rosters",
    "roster_units",
}
_REQUIRED_COLUMNS = {
    "users": {"id", "username", "password_hash", "is_admin"},
    "armies": {"id", "name", "owner_id"},
    "unit_templates": {
        "id", "army_id", "owner_id", "name", "models_per_unit", "defense",
        "toughness", "passive_abilities_json", "special_abilities_json",
        "profiles_json", "ruleset_version", "position",
    },
    "rosters": {
        "id", "name", "owner_id", "army_id", "points_limit",
        "ruleset_version", "custom_stats_enabled",
    },
    "roster_units": {
        "id", "roster_id", "source_template_id", "name", "models_per_unit",
        "unit_copies", "defense", "toughness", "passive_abilities_json",
        "special_abilities_json", "profiles_json", "position", "unit_cost",
    },
}
MAX_RESTORE_BYTES = 128 * 1024 * 1024
_COPY_CHUNK_BYTES = 1024 * 1024
_CLEANUP_RETRY_SECONDS = 5
_CLEANUP_SLEEP_SECONDS = 0.1


def _sqlite_sidecar_paths(db_path: Path) -> tuple[Path, Path]:
    return (
        db_path.with_name(f"{db_path.name}-wal"),
        db_path.with_name(f"{db_path.name}-shm"),
    )


def _remove_sqlite_sidecars(db_path: Path) -> None:
    wal_path, shm_path = _sqlite_sidecar_paths(db_path)
    for sidecar in (wal_path, shm_path):
        with contextlib.suppress(FileNotFoundError):
            deadline = time.monotonic() + _CLEANUP_RETRY_SECONDS
            while True:
                try:
                    sidecar.unlink()
                    break
                except PermissionError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(_CLEANUP_SLEEP_SECONDS)


def _checkpoint_sqlite(db_path: Path) -> None:
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error as exc:
        raise DBRestoreError(
            "Nie udało się spójnie przetworzyć dziennika WAL bazy danych."
        ) from exc


class DBRestoreError(Exception):
    """Raised when restoring the database fails."""


def resolve_sqlite_path() -> Path:
    if not DB_URL.startswith("sqlite"):
        raise DBRestoreError(
            "Przywracanie jest dostępne tylko dla bazy danych SQLite."
        )

    raw_path = DB_URL.split("///")[-1]
    db_path = Path(raw_path).expanduser()
    if not db_path.is_absolute():
        db_path = (_PROJECT_ROOT / db_path).resolve()
    return db_path


def _validate_sqlite_file(path: Path) -> None:
    try:
        uri = f"file:{path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise DBRestoreError("Przesłana baza SQLite jest uszkodzona.")
            cursor = conn.execute(
                f"""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name IN ({",".join(["?"] * len(_REQUIRED_TABLES))})
                """,
                tuple(_REQUIRED_TABLES),
            )
            tables = {row[0] for row in cursor.fetchall()}
            columns = {
                table: {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
                for table in tables
            }
    except sqlite3.Error as exc:
        raise DBRestoreError("Przesłany plik nie jest prawidłową bazą SQLite.") from exc

    missing = _REQUIRED_TABLES - tables
    if missing:
        raise DBRestoreError("Brakuje wymaganych tabel w bazie danych.")
    invalid_tables = [
        table
        for table, required in _REQUIRED_COLUMNS.items()
        if not required.issubset(columns.get(table, set()))
    ]
    if invalid_tables:
        raise DBRestoreError("Struktura tabel bazy danych nie jest zgodna z OPOS.")


def _upgrade_sqlite_file(path: Path) -> None:
    """Upgrade a validated temporary database before it replaces live data."""
    from ..db import upgrade_opos_database

    temporary_engine = create_engine(
        f"sqlite:///{path.as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    try:
        upgrade_opos_database(temporary_engine)
    finally:
        temporary_engine.dispose()


def _copy_upload_limited(source, target: Path) -> None:
    copied = 0
    with target.open("wb") as buffer:
        while chunk := source.read(_COPY_CHUNK_BYTES):
            copied += len(chunk)
            if copied > MAX_RESTORE_BYTES:
                raise DBRestoreError("Przesłana baza przekracza limit 128 MB.")
            buffer.write(chunk)
        buffer.flush()
        os.fsync(buffer.fileno())


def _copy_sqlite_with_sidecars(source: Path, target: Path) -> None:
    _checkpoint_sqlite(source)
    sidecars = _sqlite_sidecar_paths(source)
    target_sidecars = _sqlite_sidecar_paths(target)

    try:
        with sqlite3.connect(source) as source_conn, sqlite3.connect(target) as dest_conn:
            source_conn.backup(dest_conn)
    except sqlite3.Error as exc:
        raise DBRestoreError(
            "Nie udało się utworzyć kopii zapasowej bazy danych."
        ) from exc

    for source_sidecar, target_sidecar in zip(sidecars, target_sidecars):
        if source_sidecar.exists():
            shutil.copy2(source_sidecar, target_sidecar)


def _close_active_sessions() -> None:
    with contextlib.suppress(Exception):
        close_all_sessions()
    engine.dispose()


def _cleanup_temp_files(paths: tuple[Path, ...]) -> None:
    deadline = time.monotonic() + _CLEANUP_RETRY_SECONDS
    while True:
        try:
            for path in paths:
                path.unlink(missing_ok=True)
            break
        except PermissionError:
            if time.monotonic() >= deadline:
                break
            time.sleep(_CLEANUP_SLEEP_SECONDS)


def _replace_sqlite_db(source: Path, target: Path) -> None:
    _close_active_sessions()
    _checkpoint_sqlite(source)

    deadline = time.monotonic() + _CLEANUP_RETRY_SECONDS
    replace_error: str | None = None
    while True:
        try:
            os.replace(source, target)
            break
        except PermissionError:
            if time.monotonic() >= deadline:
                replace_error = (
                    "Nie udało się podmienić pliku bazy danych, ponieważ jest używany przez inny proces."
                )
                break
            time.sleep(_CLEANUP_SLEEP_SECONDS)

    if replace_error is not None:
        try:
            _copy_sqlite_with_sidecars(source, target)
        except Exception as exc:
            raise DBRestoreError(replace_error) from exc

    _remove_sqlite_sidecars(target)


def restore_sqlite_database(
    upload_file: UploadFile, *, destination_path: Path | None = None
) -> Path:
    if not upload_file:
        raise DBRestoreError("Nie przesłano pliku bazy danych.")

    target_path = destination_path or resolve_sqlite_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=DATA_DIR, suffix=target_path.suffix or ".db"
    )
    os.close(fd)
    temp_path = Path(temp_name)
    wal_temp = temp_path.with_name(f"{temp_path.name}-wal")
    shm_temp = temp_path.with_name(f"{temp_path.name}-shm")

    try:
        upload_file.file.seek(0)
        _copy_upload_limited(upload_file.file, temp_path)

        _validate_sqlite_file(temp_path)
        _upgrade_sqlite_file(temp_path)
        _validate_sqlite_file(temp_path)
        for sidecar in (wal_temp, shm_temp):
            sidecar.unlink(missing_ok=True)

        _replace_sqlite_db(temp_path, target_path)
        _cleanup_temp_files((temp_path, wal_temp, shm_temp))
        return target_path
    except Exception as exc:
        _cleanup_temp_files((temp_path, wal_temp, shm_temp))
        if isinstance(exc, DBRestoreError):
            raise

        raise DBRestoreError("Nie udało się przywrócić bazy danych.") from exc
