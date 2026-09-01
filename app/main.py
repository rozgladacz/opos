"""FastAPI entrypoint for OPOS v1."""

from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware

from . import models
from .config import DEBUG, SECRET_KEY, SESSION_HTTPS_ONLY, TRUSTED_HOSTS
from .db import get_db, init_db
from .paths import STATIC_DIR, TEMPLATES_DIR
from .routers import admin, armies, auth, export, quote, rosters, users
from .security import get_csrf_token, get_current_user
from .services.opos_rules import scale_entry_cost


logger = logging.getLogger(__name__)
app = FastAPI(title="OPOS", debug=DEBUG)

if TRUSTED_HOSTS != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=TRUSTED_HOSTS)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    https_only=SESSION_HTTPS_ONLY,
    same_site="lax",
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.on_event("startup")
def startup_event() -> None:
    init_db()
    logger.info("OPOS started")


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User | None = Depends(get_current_user(optional=True)),
):
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=303)
    armies_list = db.execute(
        select(models.Army)
        .where(models.Army.owner_id == user.id)
        .order_by(models.Army.updated_at.desc())
        .limit(5)
    ).scalars().all()
    rosters_list = db.execute(
        select(models.Roster)
        .options(selectinload(models.Roster.roster_units))
        .where(models.Roster.owner_id == user.id)
        .order_by(models.Roster.updated_at.desc())
        .limit(5)
    ).scalars().all()
    roster_rows = [
        {
            "roster": roster,
            "total_cost": sum(
                scale_entry_cost(
                    unit.unit_cost, unit.unit_copies, roster.points_scale
                )
                for unit in roster.roster_units
            ),
        }
        for roster in rosters_list
    ]
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "user": user,
            "armies": armies_list,
            "rosters": rosters_list,
            "roster_rows": roster_rows,
            "csrf_token": get_csrf_token(request),
        },
    )


app.include_router(auth.router)
app.include_router(quote.router)
app.include_router(armies.router)
app.include_router(rosters.router)
app.include_router(export.router)
app.include_router(users.router)
app.include_router(admin.router)


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> RedirectResponse:
    return RedirectResponse(url="/static/favicon.svg")
