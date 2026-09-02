"""Regression tests for one-time administrator bootstrap secrets."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import config, db, models
from app.security import hash_password, verify_password


def _temporary_database(monkeypatch, path: Path):
    database_url = f"sqlite:///{path}"
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
        future=True,
    )
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    monkeypatch.setattr(db, "DB_URL", database_url)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", session_factory)
    return engine, session_factory


def test_existing_admin_does_not_create_bootstrap_secret(
    tmp_path: Path, monkeypatch
) -> None:
    secrets_dir = tmp_path / "data"
    engine, session_factory = _temporary_database(
        monkeypatch, tmp_path / "existing.db"
    )
    db.Base.metadata.create_all(engine)
    with session_factory.begin() as session:
        session.add(
            models.User(
                username="admin",
                password_hash=hash_password("existing-password"),
                is_admin=True,
            )
        )

    monkeypatch.setattr(config, "DATA_DIR", secrets_dir)
    monkeypatch.delenv("INITIAL_ADMIN_PASSWORD", raising=False)

    db.init_db()

    assert not (secrets_dir / ".initial_admin_password").exists()
    engine.dispose()


def test_fresh_database_creates_protected_bootstrap_secret(
    tmp_path: Path, monkeypatch
) -> None:
    secrets_dir = tmp_path / "data"
    engine, session_factory = _temporary_database(
        monkeypatch, tmp_path / "fresh.db"
    )
    monkeypatch.setattr(config, "DATA_DIR", secrets_dir)
    monkeypatch.delenv("INITIAL_ADMIN_PASSWORD", raising=False)

    db.init_db()

    secret_path = secrets_dir / ".initial_admin_password"
    bootstrap_password = secret_path.read_text(encoding="utf-8").strip()
    with session_factory() as session:
        admin = session.execute(
            select(models.User).where(models.User.username == "admin")
        ).scalar_one()
    assert bootstrap_password
    assert verify_password(bootstrap_password, admin.password_hash)
    if os.name != "nt":
        assert stat.S_IMODE(secret_path.stat().st_mode) == 0o600
    engine.dispose()
