"""Testy blokowania rejestracji i tworzenia kont przez admina."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import models  # noqa: E402
from app.db import Base  # noqa: E402
from app.routers import users as users_router  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.settings import get_registration_open, set_registration_open  # noqa: E402

CSRF_TOKEN = "test-csrf-token"

# ── helpers ───────────────────────────────────────────────────────────────────

def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(bind=engine)


def _seed_admin(session: Session, username: str = "admin") -> models.User:
    user = models.User(username=username, password_hash=hash_password("admin"), is_admin=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _seed_user(session: Session, username: str = "gracz") -> models.User:
    user = models.User(username=username, password_hash=hash_password("haslo"), is_admin=False)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _fake_request() -> SimpleNamespace:
    return SimpleNamespace(query_params={}, session={"csrf_token": CSRF_TOKEN})


@pytest.fixture(autouse=True)
def _restore_registration():
    set_registration_open(True)
    yield
    set_registration_open(True)


# ── settings.py unit tests ────────────────────────────────────────────────────

class TestSettingsService:
    def test_default_is_open(self):
        assert get_registration_open() is True

    def test_set_closed(self):
        set_registration_open(False)
        assert get_registration_open() is False

    def test_set_open_again(self):
        set_registration_open(False)
        set_registration_open(True)
        assert get_registration_open() is True

    def test_env_override_true(self, monkeypatch):
        set_registration_open(False)
        monkeypatch.setenv("REGISTRATION_OPEN", "true")
        assert get_registration_open() is True

    def test_env_override_false(self, monkeypatch):
        set_registration_open(True)
        monkeypatch.setenv("REGISTRATION_OPEN", "false")
        assert get_registration_open() is False


# ── toggle endpoint ───────────────────────────────────────────────────────────

class TestRegistrationToggleEndpoint:
    def test_toggle_closes_when_open(self):
        session = _build_session()
        admin = _seed_admin(session)
        set_registration_open(True)

        resp = users_router.toggle_registration(
            request=_fake_request(), csrf_token=CSRF_TOKEN, current_user=admin
        )

        assert resp.status_code == 303
        assert not get_registration_open()
        assert "registration-closed" in resp.headers["location"]

    def test_toggle_opens_when_closed(self):
        session = _build_session()
        admin = _seed_admin(session)
        set_registration_open(False)

        resp = users_router.toggle_registration(
            request=_fake_request(), csrf_token=CSRF_TOKEN, current_user=admin
        )

        assert resp.status_code == 303
        assert get_registration_open()
        assert "registration-opened" in resp.headers["location"]

    def test_toggle_requires_admin(self):
        session = _build_session()
        regular = _seed_user(session)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            users_router.toggle_registration(
                request=_fake_request(), csrf_token=CSRF_TOKEN, current_user=regular
            )
        assert exc_info.value.status_code == 403


# ── create user endpoint ──────────────────────────────────────────────────────

class TestAdminCreateUser:
    def test_creates_regular_user(self):
        session = _build_session()
        admin = _seed_admin(session)

        resp = users_router.create_user(
            request=_fake_request(),
            csrf_token=CSRF_TOKEN,
            username="nowak",
            password="haslo123",
            db=session,
            current_user=admin,
        )

        assert resp.status_code == 303
        assert "created" in resp.headers["location"]
        created = session.execute(
            select(models.User).where(models.User.username == "nowak")
        ).scalar_one_or_none()
        assert created is not None
        assert not created.is_admin

    def test_created_user_is_never_admin(self):
        """Nowe konta zawsze mają is_admin=False, bez wyjątków."""
        session = _build_session()
        admin = _seed_admin(session)

        users_router.create_user(
            request=_fake_request(),
            csrf_token=CSRF_TOKEN,
            username="koadmin",
            password="tajne123",
            db=session,
            current_user=admin,
        )

        created = session.execute(
            select(models.User).where(models.User.username == "koadmin")
        ).scalar_one_or_none()
        assert created is not None
        assert not created.is_admin

    def test_duplicate_username_rejected(self):
        """Duplikat nazwy — użytkownik NIE zostaje dodany do bazy."""
        session = _build_session()
        admin = _seed_admin(session)
        _seed_user(session, username="duplikat")

        before = session.execute(select(models.User)).scalars().all()
        # Endpoint renderuje template przy błędzie — testujemy przez DB state.
        try:
            users_router.create_user(
                request=_fake_request(),
                csrf_token=CSRF_TOKEN,
                username="duplikat",
                password="haslo123",
                db=session,
                current_user=admin,
            )
        except Exception:
            pass
        after = session.execute(select(models.User)).scalars().all()
        # Liczba użytkowników nie powinna wzrosnąć
        assert len(after) == len(before)

    def test_short_password_does_not_create_user(self):
        """Krótkie hasło — użytkownik NIE zostaje dodany."""
        session = _build_session()
        admin = _seed_admin(session)

        try:
            users_router.create_user(
                request=_fake_request(),
                csrf_token=CSRF_TOKEN,
                username="ktos",
                password="ab",
                db=session,
                current_user=admin,
            )
        except Exception:
            pass
        created = session.execute(
            select(models.User).where(models.User.username == "ktos")
        ).scalar_one_or_none()
        assert created is None

    def test_empty_username_does_not_create_user(self):
        """Pusta nazwa użytkownika — brak rekordu w DB."""
        session = _build_session()
        admin = _seed_admin(session)

        try:
            users_router.create_user(
                request=_fake_request(),
                csrf_token=CSRF_TOKEN,
                username="   ",
                password="haslo123",
                db=session,
                current_user=admin,
            )
        except Exception:
            pass
        # Nazwa "   " po strip() jest pusta — nie powinno powstać konto
        all_users = session.execute(select(models.User)).scalars().all()
        assert not any(u.username.strip() == "" for u in all_users)

    def test_requires_admin(self):
        session = _build_session()
        regular = _seed_user(session)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            users_router.create_user(
                request=_fake_request(),
                csrf_token=CSRF_TOKEN,
                username="haker",
                password="haslo123",
                db=session,
                current_user=regular,
            )
        assert exc_info.value.status_code == 403

    def test_username_with_js_injection_chars_rejected(self):
        """Nazwa z cudzysłowem/nawiasami (próba wstrzyknięcia JS) — konto nie powstaje."""
        session = _build_session()
        admin = _seed_admin(session)

        payload = "'); alert(1);//"
        try:
            users_router.create_user(
                request=_fake_request(),
                csrf_token=CSRF_TOKEN,
                username=payload,
                password="haslo123",
                db=session,
                current_user=admin,
            )
        except Exception:
            pass
        created = session.execute(
            select(models.User).where(models.User.username == payload)
        ).scalar_one_or_none()
        assert created is None


# ── walidacja nazwy użytkownika ───────────────────────────────────────────────

class TestUsernameValidation:
    def test_accepts_plain_names(self):
        from app.security import is_valid_username
        assert is_valid_username("admin")
        assert is_valid_username("Gracz_1")
        assert is_valid_username("jan.kowalski")
        assert is_valid_username("Żółć-99")
        assert is_valid_username("dwa słowa")

    def test_rejects_dangerous_chars(self):
        from app.security import is_valid_username
        assert not is_valid_username("'); alert(1);//")
        assert not is_valid_username('<script>')
        assert not is_valid_username('a"b')
        assert not is_valid_username("a'b")
        assert not is_valid_username("a&b")
        assert not is_valid_username("a/b")

    def test_rejects_empty_and_overlong(self):
        from app.security import is_valid_username, USERNAME_MAX_LENGTH
        assert not is_valid_username("")
        assert not is_valid_username("a" * (USERNAME_MAX_LENGTH + 1))
