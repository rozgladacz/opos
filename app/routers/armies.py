"""Prywatne Armie OPOS jako prosta biblioteka snapshotów oddziałów."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import models
from ..config import OPOS_RULESET_VERSION
from ..db import get_db
from ..paths import TEMPLATES_DIR
from ..security import get_csrf_token, get_current_user, require_csrf, validate_csrf
from ..services.opos_rules import (
    QuoteValidationError,
    UnitQuoteInput,
    calculate_unit_quote,
    display_number,
)
from ..services.opos_units import (
    apply_request_to_roster_unit,
    create_template_from_roster_unit,
)


router = APIRouter(prefix="/armies", tags=["armies"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["stat"] = display_number
current_user_dep = get_current_user()


def _owned_army(db: Session, army_id: int, user_id: int) -> models.Army:
    army = db.execute(
        select(models.Army).where(
            models.Army.id == army_id,
            models.Army.owner_id == user_id,
        )
    ).scalar_one_or_none()
    if army is None:
        raise HTTPException(status_code=404, detail="Armia nie istnieje")
    return army


def _owned_template(
    db: Session, army_id: int, template_id: int, user_id: int
) -> models.UnitTemplate:
    template = db.execute(
        select(models.UnitTemplate)
        .join(models.Army)
        .where(
            models.UnitTemplate.id == template_id,
            models.UnitTemplate.army_id == army_id,
            models.Army.owner_id == user_id,
        )
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="Szablon nie istnieje")
    return template


def _clean_name(value: str, *, label: str) -> str:
    name = value.strip()
    if not name or len(name) > 120:
        raise HTTPException(status_code=422, detail=f"{label} musi mieć 1-120 znaków")
    return name


@router.get("", response_class=HTMLResponse)
def list_armies(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
):
    armies = db.execute(
        select(models.Army)
        .options(selectinload(models.Army.templates))
        .where(models.Army.owner_id == user.id)
        .order_by(models.Army.name, models.Army.id)
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "armies_list.html",
        {
            "request": request,
            "user": user,
            "armies": armies,
            "csrf_token": get_csrf_token(request),
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_army_form(
    request: Request, user: models.User = Depends(current_user_dep)
):
    return templates.TemplateResponse(
        request,
        "army_form.html",
        {"request": request, "user": user, "csrf_token": get_csrf_token(request)},
    )


@router.post("")
def create_army(
    request: Request,
    name: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> RedirectResponse:
    validate_csrf(request, csrf_token)
    army = models.Army(
        name=_clean_name(name, label="Nazwa Armii"),
        owner_id=user.id,
    )
    db.add(army)
    db.commit()
    return RedirectResponse(url=f"/armies/{army.id}", status_code=303)


@router.get("/{army_id}", response_class=HTMLResponse)
def army_detail(
    army_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
):
    army = db.execute(
        select(models.Army)
        .options(selectinload(models.Army.templates))
        .where(models.Army.id == army_id, models.Army.owner_id == user.id)
    ).scalar_one_or_none()
    if army is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "army_edit.html",
        {
            "request": request,
            "user": user,
            "army": army,
            "csrf_token": get_csrf_token(request),
        },
    )


@router.post("/{army_id}")
def rename_army(
    army_id: int,
    request: Request,
    name: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> RedirectResponse:
    validate_csrf(request, csrf_token)
    army = _owned_army(db, army_id, user.id)
    army.name = _clean_name(name, label="Nazwa Armii")
    db.commit()
    return RedirectResponse(url=f"/armies/{army.id}", status_code=303)


@router.post("/{army_id}/delete")
def delete_army(
    army_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> RedirectResponse:
    validate_csrf(request, csrf_token)
    db.delete(_owned_army(db, army_id, user.id))
    db.commit()
    return RedirectResponse(url="/armies", status_code=303)


@router.post("/{army_id}/templates", dependencies=[Depends(require_csrf)])
def create_template(
    army_id: int,
    payload: UnitQuoteInput,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> dict[str, object]:
    army = _owned_army(db, army_id, user.id)
    request = payload.model_copy(
        update={
            "unit_copies": 1,
            "shield_fist_enabled": False,
        }
    )
    try:
        quote = calculate_unit_quote(request, ruleset_version=OPOS_RULESET_VERSION)
    except QuoteValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    transient = models.RosterUnit(
        name="",
        models_per_unit=1,
        unit_copies=1,
        defense=1,
        toughness=1,
        profiles_json="{}",
        position=0,
        unit_cost=0,
    )
    apply_request_to_roster_unit(transient, request, quote)
    position = db.execute(
        select(func.coalesce(func.max(models.UnitTemplate.position), -1)).where(
            models.UnitTemplate.army_id == army.id
        )
    ).scalar_one() + 1
    template = create_template_from_roster_unit(
        transient,
        army=army,
        position=position,
        ruleset_version=OPOS_RULESET_VERSION,
    )
    db.add(template)
    db.commit()
    return {"id": template.id, "name": template.name}


@router.patch(
    "/{army_id}/templates/{template_id}", dependencies=[Depends(require_csrf)]
)
def replace_template(
    army_id: int,
    template_id: int,
    payload: UnitQuoteInput,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> dict[str, object]:
    template = _owned_template(db, army_id, template_id, user.id)
    request = payload.model_copy(
        update={
            "unit_copies": 1,
            "shield_fist_enabled": False,
        }
    )
    try:
        quote = calculate_unit_quote(request, ruleset_version=OPOS_RULESET_VERSION)
    except QuoteValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    transient = models.RosterUnit(
        name="",
        models_per_unit=1,
        unit_copies=1,
        defense=1,
        toughness=1,
        profiles_json="{}",
        position=0,
        unit_cost=0,
    )
    apply_request_to_roster_unit(transient, request, quote)
    template.name = transient.name
    template.models_per_unit = transient.models_per_unit
    template.defense = transient.defense
    template.toughness = transient.toughness
    template.passive_abilities_json = transient.passive_abilities_json
    template.special_abilities_json = transient.special_abilities_json
    template.profiles_json = transient.profiles_json
    template.ruleset_version = OPOS_RULESET_VERSION
    db.commit()
    return {"id": template.id, "name": template.name}


@router.delete(
    "/{army_id}/templates/{template_id}",
    status_code=204,
    dependencies=[Depends(require_csrf)],
)
def delete_template(
    army_id: int,
    template_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> Response:
    db.delete(_owned_template(db, army_id, template_id, user.id))
    db.commit()
    return Response(status_code=204)
