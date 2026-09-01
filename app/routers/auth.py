"""Logowanie i rejestracja OPOS z ochroną login-CSRF."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..paths import TEMPLATES_DIR
from ..security import (
    get_csrf_token,
    get_current_user,
    hash_password,
    is_valid_username,
    validate_csrf,
    verify_password,
)
from ..services.settings import get_registration_open


router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _auth_context(request: Request, **extra: object) -> dict[str, object]:
    return {"request": request, "csrf_token": get_csrf_token(request), **extra}


@router.get("/login", response_class=HTMLResponse)
def login_form(
    request: Request,
    current_user: models.User | None = Depends(get_current_user(optional=True)),
):
    if current_user:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request, "auth_login.html", _auth_context(request, error=None)
    )


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    validate_csrf(request, csrf_token)
    user = db.execute(
        select(models.User).where(models.User.username == username)
    ).scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "auth_login.html",
            _auth_context(request, error="Nieprawidłowy login lub hasło"),
            status_code=400,
        )
    request.session.clear()
    request.session["user_id"] = user.id
    get_csrf_token(request)
    return RedirectResponse(url="/", status_code=303)


@router.get("/register", response_class=HTMLResponse)
def register_form(
    request: Request,
    current_user: models.User | None = Depends(get_current_user(optional=True)),
):
    if current_user:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request,
        "auth_register.html",
        _auth_context(
            request, error=None, registration_open=get_registration_open()
        ),
    )


@router.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    validate_csrf(request, csrf_token)
    registration_open = get_registration_open()
    if not registration_open:
        return templates.TemplateResponse(
            request,
            "auth_register.html",
            _auth_context(request, error=None, registration_open=False),
            status_code=403,
        )
    username = username.strip()
    if not is_valid_username(username):
        return templates.TemplateResponse(
            request,
            "auth_register.html",
            _auth_context(
                request,
                error="Nazwa może zawierać litery, cyfry, spację oraz . _ -",
                registration_open=True,
            ),
            status_code=400,
        )
    if len(password) < 4:
        return templates.TemplateResponse(
            request,
            "auth_register.html",
            _auth_context(
                request,
                error="Hasło musi zawierać co najmniej 4 znaki.",
                registration_open=True,
            ),
            status_code=400,
        )
    existing = db.execute(
        select(models.User).where(models.User.username == username)
    ).scalar_one_or_none()
    if existing:
        return templates.TemplateResponse(
            request,
            "auth_register.html",
            _auth_context(
                request,
                error="Użytkownik o takiej nazwie już istnieje",
                registration_open=True,
            ),
            status_code=400,
        )
    user = models.User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    request.session.clear()
    request.session["user_id"] = user.id
    get_csrf_token(request)
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
def logout(
    request: Request, csrf_token: str = Form(...)
) -> RedirectResponse:
    validate_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse(url="/auth/login", status_code=303)
