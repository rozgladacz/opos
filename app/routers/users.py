from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
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
)
from ..services import backup as backup_service
from ..services import db_restore
from ..services.settings import get_registration_open, set_registration_open

router = APIRouter(prefix="/users", tags=["users"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _require_admin(user: models.User) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Brak uprawnień")


def _render_user_list(
    request: Request,
    db: Session,
    current_user: models.User,
    *,
    message: str | None = None,
    error: str | None = None,
    error_user_id: int | None = None,
    create_error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    users = (
        db.execute(select(models.User).order_by(models.User.username))
        .scalars()
        .all()
    )
    return templates.TemplateResponse(
        request,
        "users_list.html",
        {
            "request": request,
            "user": current_user,
            "users": users,
            "message": message,
            "error": error,
            "error_user_id": error_user_id,
            "create_error": create_error,
            "registration_open": get_registration_open(),
            "csrf_token": get_csrf_token(request),
        },
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def list_users(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user()),
):
    _require_admin(current_user)
    status_key = request.query_params.get("status")
    detail = request.query_params.get("detail")
    message_map = {
        "password-changed": "Hasło użytkownika zostało zaktualizowane.",
        "deleted": "Użytkownik został usunięty.",
        "created": "Konto zostało utworzone.",
        "registration-opened": "Rejestracja publiczna została włączona.",
        "registration-closed": "Rejestracja publiczna została wyłączona.",
        "restore-ok": detail or "Baza danych została przywrócona.",
    }
    message = message_map.get(status_key)

    error_key = request.query_params.get("error")
    error_map = {
        "self-delete": "Nie można usunąć własnego konta.",
        "missing-user": "Użytkownik nie istnieje.",
        "restore-error": detail or "Przywracanie bazy danych nie powiodło się.",
    }
    error = error_map.get(error_key)

    target = request.query_params.get("target")
    error_user_id = int(target) if target and target.isdigit() else None

    return _render_user_list(
        request,
        db,
        current_user,
        message=message,
        error=error,
        error_user_id=error_user_id,
    )


@router.post("/backup")
def download_backup(
    request: Request,
    csrf_token: str = Form(...),
    current_user: models.User = Depends(get_current_user()),
) -> FileResponse:
    _require_admin(current_user)
    validate_csrf(request, csrf_token)
    try:
        backup_path = backup_service.create_backup()
    except db_restore.DBRestoreError as exc:  # pragma: no cover - guarded by config
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except backup_service.BackupError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return FileResponse(
        backup_path,
        filename=backup_path.name,
        media_type="application/octet-stream",
    )


@router.post("/{user_id}/password")
def change_password(
    user_id: int,
    request: Request,
    new_password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user()),
):
    _require_admin(current_user)
    validate_csrf(request, csrf_token)
    target_user = db.get(models.User, user_id)
    if not target_user:
        raise HTTPException(status_code=404)

    password = new_password.strip()
    if len(password) < 4:
        return _render_user_list(
            request,
            db,
            current_user,
            error="Hasło musi zawierać co najmniej 4 znaki.",
            error_user_id=user_id,
            status_code=400,
        )

    target_user.password_hash = hash_password(password)
    db.commit()
    return RedirectResponse(url="/users?status=password-changed", status_code=303)


@router.post("/{user_id}/delete")
def delete_user(
    user_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user()),
):
    _require_admin(current_user)
    validate_csrf(request, csrf_token)
    target_user = db.get(models.User, user_id)
    if not target_user:
        raise HTTPException(status_code=404)

    if target_user.id == current_user.id:
        return RedirectResponse(
            url=f"/users?error=self-delete&target={user_id}",
            status_code=303,
        )

    db.delete(target_user)
    db.commit()
    return RedirectResponse(url="/users?status=deleted", status_code=303)


@router.post("/create")
def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user()),
):
    _require_admin(current_user)
    validate_csrf(request, csrf_token)

    username = username.strip()
    password = password.strip()

    if not username:
        return _render_user_list(
            request, db, current_user,
            create_error="Nazwa użytkownika nie może być pusta.",
            status_code=400,
        )
    if not is_valid_username(username):
        return _render_user_list(
            request, db, current_user,
            create_error="Nazwa użytkownika może zawierać tylko litery, cyfry, spację oraz znaki . _ -",
            status_code=400,
        )
    if len(password) < 4:
        return _render_user_list(
            request, db, current_user,
            create_error="Hasło musi mieć co najmniej 4 znaki.",
            status_code=400,
        )

    existing = db.execute(
        select(models.User).where(models.User.username == username)
    ).scalar_one_or_none()
    if existing:
        return _render_user_list(
            request, db, current_user,
            create_error=f'Użytkownik "{username}" już istnieje.',
            status_code=400,
        )

    new_user = models.User(
        username=username,
        password_hash=hash_password(password),
        is_admin=False,
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse(url="/users?status=created", status_code=303)


@router.post("/registration-toggle")
def toggle_registration(
    request: Request,
    csrf_token: str = Form(...),
    current_user: models.User = Depends(get_current_user()),
):
    _require_admin(current_user)
    validate_csrf(request, csrf_token)
    new_state = not get_registration_open()
    set_registration_open(new_state)
    status = "registration-opened" if new_state else "registration-closed"
    return RedirectResponse(url=f"/users?status={status}", status_code=303)


@router.post("/restore")
async def restore_database(
    request: Request,
    file: UploadFile = File(...),
    csrf_token: str = Form(...),
    current_user: models.User = Depends(get_current_user(close_session=True)),
) -> RedirectResponse:
    _require_admin(current_user)
    validate_csrf(request, csrf_token)

    try:
        await file.seek(0)
        db_restore.restore_sqlite_database(file)
    except db_restore.DBRestoreError as exc:
        detail = quote_plus(str(exc))
        return RedirectResponse(
            url=f"/users?status=restore-error&detail={detail}",
            status_code=303,
        )
    finally:
        await file.close()

    return RedirectResponse(url="/users?status=restore-ok", status_code=303)
