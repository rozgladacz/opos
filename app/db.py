"""Połączenie z bazą i inicjalizacja świeżego schematu OPOS."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DB_URL, INITIAL_ADMIN_PASSWORD


logger = logging.getLogger(__name__)
connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
engine = create_engine(DB_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


if DB_URL.startswith("sqlite"):

    @event.listens_for(Engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    pass


_LEGACY_SZOP_TABLES = frozenset(
    {
        "abilities",
        "armories",
        "armory_disabled_weapons",
        "army_spells",
        "rulesets",
        "unit_abilities",
        "unit_groups",
        "unit_weapons",
        "units",
        "weapons",
    }
)

_ROSTER_BOOLEAN_MODE_COLUMNS = (
    "collapse_descriptions",
    "small_battle_enabled",
    "shield_fist_enabled",
)
_USER_PREFERENCE_COLUMNS = {
    "default_custom_stats_enabled": "BOOLEAN NOT NULL DEFAULT 0",
    "default_points_scale": "INTEGER NOT NULL DEFAULT 10",
    "default_collapse_descriptions": "BOOLEAN NOT NULL DEFAULT 0",
    "default_small_battle_enabled": "BOOLEAN NOT NULL DEFAULT 0",
    "default_shield_fist_enabled": "BOOLEAN NOT NULL DEFAULT 0",
}


def assert_not_legacy_szop_database(bind: Engine) -> None:
    """Refuse an in-place SZOP-to-OPOS conversion.

    OPOS intentionally starts from a fresh database. Creating the new tables next
    to an old schema would leave a database that appears usable while mixing two
    incompatible domains.
    """
    legacy_tables = sorted(set(inspect(bind).get_table_names()) & _LEGACY_SZOP_TABLES)
    if legacy_tables:
        joined = ", ".join(legacy_tables)
        raise RuntimeError(
            "Wykryto bazę SZOP (tabele: "
            f"{joined}). OPOS wymaga świeżej bazy data/opos.db; "
            "zachowaj starą bazę jako archiwum i ustaw osobny DB_URL."
        )


def ensure_roster_mode_columns(bind: Engine) -> None:
    """Upgrade pre-mode SQLite databases without touching their OPOS data."""
    if bind.dialect.name != "sqlite":
        return
    inspector = inspect(bind)
    if "rosters" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("rosters")}
    missing_boolean = [
        name for name in _ROSTER_BOOLEAN_MODE_COLUMNS if name not in existing
    ]
    points_scale_missing = "points_scale" not in existing
    if not missing_boolean and not points_scale_missing:
        return
    with bind.begin() as connection:
        for name in missing_boolean:
            connection.exec_driver_sql(
                f"ALTER TABLE rosters ADD COLUMN {name} "
                "BOOLEAN NOT NULL DEFAULT 0"
            )
        if points_scale_missing:
            connection.exec_driver_sql(
                "ALTER TABLE rosters ADD COLUMN points_scale "
                "INTEGER NOT NULL DEFAULT 10"
            )
            if "simple_points_enabled" in existing:
                connection.exec_driver_sql(
                    "UPDATE rosters SET points_scale = "
                    "CASE WHEN simple_points_enabled = 1 THEN 10 ELSE 1 END"
                )


def ensure_user_preference_columns(bind: Engine) -> None:
    """Add per-user defaults used by the new-roster form."""
    if bind.dialect.name != "sqlite":
        return
    inspector = inspect(bind)
    if "users" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("users")}
    missing = {
        name: definition
        for name, definition in _USER_PREFERENCE_COLUMNS.items()
        if name not in existing
    }
    if not missing:
        return
    with bind.begin() as connection:
        for name, definition in missing.items():
            connection.exec_driver_sql(
                f"ALTER TABLE users ADD COLUMN {name} {definition}"
            )


def drop_legacy_simple_points_column(bind: Engine) -> None:
    """Remove the superseded boolean after its data has been converted."""
    if bind.dialect.name != "sqlite":
        return
    inspector = inspect(bind)
    if "rosters" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("rosters")}
    if "simple_points_enabled" not in existing:
        return
    with bind.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE rosters DROP COLUMN simple_points_enabled"
        )


def drop_legacy_army_shield_fist_column(bind: Engine) -> None:
    """Remove the v3.0 Army-level mode after copying it to rosters."""
    if bind.dialect.name != "sqlite":
        return
    inspector = inspect(bind)
    if "armies" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("armies")}
    if "shield_fist_enabled" not in existing:
        return
    with bind.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE armies DROP COLUMN shield_fist_enabled"
        )


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def upgrade_opos_database(bind: Engine) -> int:
    """Upgrade one OPOS database inside its own atomic transaction."""
    from . import models  # noqa: F401 - register all tables on Base.metadata
    from .services.opos_units import (
        migrate_opos_1_2,
        migrate_opos_1_3,
        migrate_opos_v3,
        migrate_opos_v3_1,
    )

    assert_not_legacy_szop_database(bind)
    ensure_roster_mode_columns(bind)
    ensure_user_preference_columns(bind)
    Base.metadata.create_all(bind=bind)
    local_session = sessionmaker(
        bind=bind, autoflush=False, autocommit=False, future=True
    )
    with local_session.begin() as session:
        migrated = migrate_opos_1_2(session)
        migrated += migrate_opos_1_3(session)
        migrated += migrate_opos_v3(session)
        migrated += migrate_opos_v3_1(session)
    drop_legacy_simple_points_column(bind)
    drop_legacy_army_shield_fist_column(bind)
    return migrated


def init_db() -> None:
    """Create a fresh OPOS schema and a securely bootstrapped administrator."""
    from . import models
    from .security import hash_password
    from .services.opos_units import normalize_legacy_snapshot_records

    if DB_URL.startswith("sqlite"):
        raw_path = DB_URL.split("///", maxsplit=1)[-1]
        db_path = Path(raw_path)
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)

    migrated = upgrade_opos_database(engine)
    if migrated:
        logger.info("Zmigrowano %s snapshotów OPOS.", migrated)
    with SessionLocal.begin() as session:
        normalized = normalize_legacy_snapshot_records(session)
        if normalized:
            logger.info(
                "Przeniesiono Szarżę/Przygotowanie do profili ataku w %s snapshotach.",
                normalized,
            )
        admin = session.execute(
            select(models.User).where(models.User.username == "admin")
        ).scalar_one_or_none()
        if admin is None:
            session.add(
                models.User(
                    username="admin",
                    password_hash=hash_password(INITIAL_ADMIN_PASSWORD),
                    is_admin=True,
                )
            )
            logger.warning(
                "Utworzono administratora 'admin'. Hasło bootstrap znajduje się "
                "w chronionym pliku DATA_DIR/.initial_admin_password albo w zmiennej "
                "INITIAL_ADMIN_PASSWORD. Zmień je po pierwszym logowaniu."
            )
