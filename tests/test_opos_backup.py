import io
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from sqlalchemy import create_engine

from app.db import Base
from app.routers import users
from app.services import backup, db_restore
from app.services.opos_units import OPOS_V3_1_USER_VERSION


def _database(path: Path, tables: set[str]) -> None:
    with sqlite3.connect(path) as connection:
        for table in tables:
            connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')


def test_restore_accepts_fresh_opos_schema(tmp_path: Path) -> None:
    path = tmp_path / "opos.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()

    db_restore._validate_sqlite_file(path)


def test_restore_upgrades_temporary_database_before_replacement(tmp_path: Path) -> None:
    path = tmp_path / "opos-old.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()

    db_restore._upgrade_sqlite_file(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (
            OPOS_V3_1_USER_VERSION
        )


def test_restore_rejects_legacy_szop_shape(tmp_path: Path) -> None:
    path = tmp_path / "szop.db"
    _database(path, {"users", "armies", "rosters", "units", "weapons"})

    with pytest.raises(db_restore.DBRestoreError, match="wymaganych tabel"):
        db_restore._validate_sqlite_file(path)


def test_backup_filename_is_rebranded() -> None:
    assert backup.BACKUP_FILENAME_PREFIX == "opos-backup-"


def test_restore_rejects_table_names_without_opos_columns(tmp_path: Path) -> None:
    path = tmp_path / "fake-opos.db"
    _database(path, db_restore._REQUIRED_TABLES)

    with pytest.raises(db_restore.DBRestoreError, match="Struktura tabel"):
        db_restore._validate_sqlite_file(path)


def test_restore_upload_has_a_hard_size_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(db_restore, "MAX_RESTORE_BYTES", 4)
    target = tmp_path / "upload.db"

    with pytest.raises(db_restore.DBRestoreError, match="limit 128 MB"):
        db_restore._copy_upload_limited(io.BytesIO(b"12345"), target)


def test_backup_download_is_a_post_mutation_protected_by_csrf(monkeypatch) -> None:
    route = next(route for route in users.router.routes if route.path == "/users/backup")
    assert route.methods == {"POST"}

    monkeypatch.setattr(
        backup,
        "create_backup",
        lambda: (_ for _ in ()).throw(AssertionError("backup must not run")),
    )
    request = SimpleNamespace(session={"csrf_token": "valid"})
    current_user = SimpleNamespace(is_admin=True)
    with pytest.raises(HTTPException) as exc_info:
        users.download_backup(
            request=request,
            csrf_token="wrong",
            current_user=current_user,
        )
    assert exc_info.value.status_code == 403
