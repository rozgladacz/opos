from __future__ import annotations

import logging
import secrets
from urllib.parse import quote_plus

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .. import config, models
from ..paths import TEMPLATES_DIR
from ..security import (
    get_csrf_token,
    get_current_user,
    require_csrf,
    validate_csrf,
    verify_password,
)
from ..services import update_service

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
current_user_dep = get_current_user()


class UpdatePayload(BaseModel):
    ref: str | None = None
    tag: str | None = None


def _require_admin(user: models.User) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Brak uprawnień")


def _require_webhook_token(request: Request) -> None:
    expected_token = config.UPDATE_WEBHOOK_TOKEN
    if not expected_token:
        raise HTTPException(status_code=500, detail="Brak konfiguracji tokenu webhooka.")
    provided_token = request.headers.get("x-webhook-token")
    if not provided_token or not secrets.compare_digest(provided_token, expected_token):
        raise HTTPException(status_code=401, detail="Nieprawidłowy token webhooka.")


def _status_messages(status_key: str | None, detail: str | None) -> tuple[str | None, str | None]:
    if status_key == "update-ok":
        return detail or "Repozytorium zostało zaktualizowane.", None
    if status_key == "update-error":
        return None, detail or "Aktualizacja repozytorium nie powiodła się."
    return None, None


def _is_default_admin_password(user: models.User) -> bool:
    """Return True when the admin account still uses the factory-default 'admin' password."""
    if user.username != "admin" or not user.password_hash:
        return False
    try:
        return verify_password("admin", user.password_hash)
    except Exception:
        return False


@router.get("", response_class=HTMLResponse, name="admin_dashboard")
def admin_dashboard(
    request: Request, current_user: models.User = Depends(current_user_dep)
):
    _require_admin(current_user)

    status_key = request.query_params.get("status")
    detail = request.query_params.get("detail")
    message, error = _status_messages(status_key, detail)

    return templates.TemplateResponse(
        request,
        "admin_dashboard.html",
        {
            "request": request,
            "user": current_user,
            "message": message,
            "error": error,
            "warn_default_password": _is_default_admin_password(current_user),
            "app_version": config.APP_VERSION,
            "csrf_token": get_csrf_token(request),
        },
    )


@router.post("/update")
def trigger_update(
    request: Request,
    csrf_token: str = Form(...),
    current_user: models.User = Depends(current_user_dep),
) -> RedirectResponse:
    _require_admin(current_user)
    validate_csrf(request, csrf_token)
    logger.info(
        "Aktualizacja usługi uruchomiona przez użytkownika %s",
        current_user.username,
    )
    status_payload = update_service.queue_update_service()
    detail = status_payload.detail or status_payload.error
    if status_payload.status == "queued":
        message = detail or "Aktualizacja została uruchomiona."
        redirect_url = f"/admin?status=update-ok&detail={quote_plus(message)}"
    else:
        error_detail = detail or "Aktualizacja usługi nie powiodła się."
        redirect_url = f"/admin?status=update-error&detail={quote_plus(error_detail)}"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/update-job", dependencies=[Depends(require_csrf)])
def trigger_update_job(
    payload: UpdatePayload | None = Body(default=None),
    current_user: models.User = Depends(current_user_dep),
) -> dict[str, str | None]:
    _require_admin(current_user)
    payload = payload or UpdatePayload()
    logger.info(
        "Aktualizacja usługi (API) uruchomiona przez użytkownika %s",
        current_user.username,
    )
    status_payload = update_service.queue_update_service()
    if status_payload.status == "blocked":
        raise HTTPException(status_code=429, detail=status_payload.detail)
    if status_payload.status == "error":
        raise HTTPException(
            status_code=503,
            detail=status_payload.error or status_payload.detail,
        )
    target = payload.ref or (f"tag {payload.tag}" if payload.tag else None)
    return {
        "status": status_payload.status,
        "detail": status_payload.detail,
        "target": target,
        "task_id": status_payload.task_id,
    }


@router.post("/update-start", dependencies=[Depends(require_csrf)])
def trigger_update_start(
    payload: UpdatePayload | None = Body(default=None),
    current_user: models.User = Depends(current_user_dep),
) -> dict[str, str | None]:
    _require_admin(current_user)
    payload = payload or UpdatePayload()
    logger.info(
        "Aktualizacja usługi (API) uruchomiona przez użytkownika %s",
        current_user.username,
    )
    status_payload = update_service.queue_update_service()
    target = payload.ref or (f"tag {payload.tag}" if payload.tag else None)
    return {
        "status": status_payload.status,
        "detail": status_payload.detail,
        "target": target,
        "task_id": status_payload.task_id,
    }


@router.get("/update-status")
def get_update_status(current_user: models.User = Depends(current_user_dep)) -> dict[str, object]:
    _require_admin(current_user)
    return {
        "status": update_service.read_status(),
        "logs": update_service.read_logs(limit=10),
        "busy": update_service.is_update_locked(),
        "lock": update_service.read_lock_status(),
        "last": update_service.read_last_state(),
    }


@router.get("/update-state")
def get_update_state(current_user: models.User = Depends(current_user_dep)) -> dict[str, object | None]:
    _require_admin(current_user)
    return {
        "current": update_service.read_current_state(),
        "last": update_service.read_last_state(),
    }


@router.post("/update/webhook")
def trigger_update_webhook(
    background_tasks: BackgroundTasks,
    request: Request,
    payload: UpdatePayload | None = Body(default=None),
) -> dict[str, str | None]:
    _require_webhook_token(request)
    payload = payload or UpdatePayload()
    logger.info("Webhook uruchomił aktualizację repozytorium.")
    status_payload = update_service.queue_update(
        background_tasks, ref=payload.ref, tag=payload.tag
    )
    if status_payload.status == "blocked":
        raise HTTPException(status_code=429, detail=status_payload.detail)
    target = payload.ref or (f"tag {payload.tag}" if payload.tag else None)
    return {
        "status": status_payload.status,
        "detail": status_payload.detail,
        "target": target,
        "task_id": status_payload.task_id,
    }


@router.get("/update/webhook-status")
def get_update_webhook_status(request: Request, task_id: str | None = None) -> dict[str, object]:
    _require_webhook_token(request)
    status_payload = update_service.read_status()
    if task_id and status_payload and status_payload.get("task_id") != task_id:
        raise HTTPException(status_code=404, detail="Brak statusu dla podanego zadania.")
    return {
        "status": status_payload,
        "logs": update_service.read_logs(limit=10),
        "busy": update_service.is_update_locked(),
        "lock": update_service.read_lock_status(),
    }
