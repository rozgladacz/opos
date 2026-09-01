"""Rozpiski OPOS i CRUD wspólnych profili oddziałów."""

from __future__ import annotations

import json
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import models
from ..config import OPOS_RULESET_VERSION
from ..db import get_db
from ..paths import TEMPLATES_DIR
from ..security import get_csrf_token, get_current_user, require_csrf, validate_csrf
from ..services.cards import (
    build_ability_payloads,
    build_profile_payloads,
)
from ..services.opos_rules import (
    QuoteValidationError,
    UnitQuoteInput,
    calculate_unit_quote,
    display_number,
    display_stat_value,
    format_stat_value,
    normalize_snapshot_abilities,
    scale_entry_cost,
    scale_points,
    stat_label,
)
from ..services.opos_units import (
    apply_request_to_roster_unit,
    create_template_from_roster_unit,
    request_from_snapshot,
    snapshot_requires_custom_stats,
    template_requires_custom_stats,
    update_template_from_roster_unit,
)


router = APIRouter(prefix="/rosters", tags=["rosters"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["stat"] = display_number
templates.env.globals["display_stat"] = format_stat_value
current_user_dep = get_current_user()


class TemplateCopyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: int
    enable_custom_stats: bool = False
    unit_copies: int = Field(default=1, ge=1, le=999)


class SaveTemplatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    army_id: int


class ReorderPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_ids: list[int]


def _owned_roster(db: Session, roster_id: int, user_id: int) -> models.Roster:
    roster = db.execute(
        select(models.Roster).where(
            models.Roster.id == roster_id,
            models.Roster.owner_id == user_id,
        )
    ).scalar_one_or_none()
    if roster is None:
        raise HTTPException(status_code=404, detail="Rozpiska nie istnieje")
    return roster


def _owned_unit_and_roster(
    db: Session, roster_id: int, unit_id: int, user_id: int
) -> tuple[models.RosterUnit, models.Roster]:
    result = db.execute(
        select(models.RosterUnit, models.Roster)
        .options(
            joinedload(models.RosterUnit.source_template).joinedload(
                models.UnitTemplate.army
            ),
        )
        .join(models.Roster, models.RosterUnit.roster_id == models.Roster.id)
        .where(
            models.RosterUnit.id == unit_id,
            models.RosterUnit.roster_id == roster_id,
            models.Roster.owner_id == user_id,
        )
    ).one_or_none()
    if result is None:
        raise HTTPException(status_code=404, detail="Oddział nie istnieje")
    return result


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


def _clean_name(value: str, label: str) -> str:
    name = value.strip()
    if not name or len(name) > 120:
        raise HTTPException(status_code=422, detail=f"{label} musi mieć 1-120 znaków")
    return name


def _calculate_for_roster(
    payload: UnitQuoteInput, roster: models.Roster
) -> tuple[UnitQuoteInput, object]:
    request = payload.model_copy(
        update={
            "custom_stats_enabled": roster.custom_stats_enabled,
            "points_scale": roster.points_scale,
            "small_battle_enabled": roster.small_battle_enabled,
            "shield_fist_enabled": roster.shield_fist_enabled,
        }
    )
    try:
        quote = calculate_unit_quote(request, ruleset_version=roster.ruleset_version)
    except QuoteValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return request, quote


def _roster_unit_payload(
    unit: models.RosterUnit, roster: models.Roster
) -> dict[str, object]:
    shield_fist_enabled = roster.shield_fist_enabled
    passive_abilities, profiles, _ = normalize_snapshot_abilities(
        json.loads(unit.passive_abilities_json),
        json.loads(unit.profiles_json),
    )
    displayed_profiles = {
        range_slug: {
            **profile,
            "strength": display_number(
                display_stat_value(
                    "strength",
                    profile["strength"],
                    shield_fist_enabled=shield_fist_enabled,
                )
            ),
        }
        for range_slug, profile in profiles.items()
    }
    source_army = unit.source_template.army if unit.source_template else None
    return {
        "id": unit.id,
        "source_template_id": unit.source_template_id,
        "name": unit.name,
        "models_per_unit": unit.models_per_unit,
        "unit_copies": unit.unit_copies,
        "defense": display_number(
            display_stat_value(
                "defense",
                unit.defense,
                shield_fist_enabled=shield_fist_enabled,
            )
        ),
        "toughness": display_number(unit.toughness),
        "passive_abilities": passive_abilities,
        "special_abilities": json.loads(unit.special_abilities_json),
        "profiles": displayed_profiles,
        "source_template_army_id": source_army.id if source_army else None,
        "source_template_army_name": source_army.name if source_army else None,
        "can_update_template": bool(
            source_army and roster.army_id == source_army.id
        ),
        "position": unit.position,
        "unit_cost": scale_points(unit.unit_cost, roster.points_scale),
        "entry_cost": scale_entry_cost(
            unit.unit_cost, unit.unit_copies, roster.points_scale
        ),
    }


@router.get("", response_class=HTMLResponse)
def list_rosters(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
):
    rosters = db.execute(
        select(models.Roster)
        .options(selectinload(models.Roster.roster_units))
        .where(models.Roster.owner_id == user.id)
        .order_by(models.Roster.updated_at.desc(), models.Roster.id.desc())
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
            "points_limit": scale_points(roster.points_limit, roster.points_scale),
        }
        for roster in rosters
    ]
    return templates.TemplateResponse(
        request,
        "rosters_list.html",
        {
            "request": request,
            "user": user,
            "rosters": rosters,
            "roster_rows": roster_rows,
            "csrf_token": get_csrf_token(request),
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_roster_form(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
):
    armies = db.execute(
        select(models.Army)
        .where(models.Army.owner_id == user.id)
        .order_by(models.Army.name)
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "roster_form.html",
        {
            "request": request,
            "user": user,
            "armies": armies,
            "csrf_token": get_csrf_token(request),
        },
    )


@router.post("")
def create_roster(
    request: Request,
    name: str = Form(...),
    csrf_token: str = Form(...),
    army_id: int | None = Form(default=None),
    points_limit: int | None = Form(default=None),
    custom_stats_enabled: bool = Form(default=False),
    points_scaling_enabled: bool = Form(default=False),
    points_scale: int = Form(default=10, ge=1, le=1_000_000),
    collapse_descriptions: bool = Form(default=False),
    small_battle_enabled: bool = Form(default=False),
    shield_fist_enabled: bool = Form(default=False),
    save_as_defaults: bool = Form(default=False),
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> RedirectResponse:
    validate_csrf(request, csrf_token)
    if points_limit is not None and points_limit <= 0:
        raise HTTPException(status_code=422, detail="Limit punktów musi być dodatni")
    if army_id is not None:
        _owned_army(db, army_id, user.id)
    effective_points_scale = points_scale if points_scaling_enabled else 1
    roster = models.Roster(
        name=_clean_name(name, "Nazwa rozpiski"),
        owner_id=user.id,
        army_id=army_id,
        points_limit=points_limit,
        ruleset_version=OPOS_RULESET_VERSION,
        custom_stats_enabled=custom_stats_enabled,
        points_scale=effective_points_scale,
        collapse_descriptions=collapse_descriptions,
        small_battle_enabled=small_battle_enabled,
        shield_fist_enabled=shield_fist_enabled,
    )
    if save_as_defaults:
        db.execute(
            update(models.User)
            .where(models.User.id == user.id)
            .values(
                default_custom_stats_enabled=custom_stats_enabled,
                default_points_scale=effective_points_scale,
                default_collapse_descriptions=collapse_descriptions,
                default_small_battle_enabled=small_battle_enabled,
                default_shield_fist_enabled=shield_fist_enabled,
            )
        )
    db.add(roster)
    db.commit()
    return RedirectResponse(url=f"/rosters/{roster.id}", status_code=303)


@router.get("/{roster_id}", response_class=HTMLResponse)
def roster_detail(
    roster_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
):
    roster_army_rows = db.execute(
        select(models.Roster, models.Army)
        .outerjoin(models.Army, models.Army.owner_id == models.Roster.owner_id)
        .options(joinedload(models.Roster.army).joinedload(models.Army.templates))
        .where(models.Roster.id == roster_id, models.Roster.owner_id == user.id)
        .order_by(models.Army.name, models.Army.id)
    ).unique().all()
    if not roster_army_rows:
        raise HTTPException(status_code=404)
    roster = roster_army_rows[0][0]
    armies = [army for _, army in roster_army_rows if army is not None]
    units = db.execute(
        select(models.RosterUnit)
        .options(
            joinedload(models.RosterUnit.source_template).joinedload(
                models.UnitTemplate.army
            )
        )
        .where(models.RosterUnit.roster_id == roster.id)
        .order_by(models.RosterUnit.position, models.RosterUnit.id)
    ).scalars().all()
    shield_fist_enabled = roster.shield_fist_enabled
    requires_custom_stats = any(
        snapshot_requires_custom_stats(
            item,
            ruleset_version=roster.ruleset_version,
            small_battle_enabled=roster.small_battle_enabled,
        )
        for item in units
    )
    unit_rows = [
        {
            "unit": item,
            "unit_cost": scale_points(item.unit_cost, roster.points_scale),
            "entry_cost": scale_entry_cost(
                item.unit_cost, item.unit_copies, roster.points_scale
            ),
            "defense": format_stat_value(
                "defense",
                item.defense,
                shield_fist_enabled=shield_fist_enabled,
            ),
            "defense_label": stat_label(
                "defense", shield_fist_enabled=shield_fist_enabled
            ),
            "toughness": display_number(item.toughness),
            "profiles": build_profile_payloads(
                item,
                ruleset_version=roster.ruleset_version,
                shield_fist_enabled=shield_fist_enabled,
            ),
            "abilities": build_ability_payloads(
                item,
                ruleset_version=roster.ruleset_version,
                small_battle_enabled=roster.small_battle_enabled,
            ),
            "source_template_army_id": (
                item.source_template.army_id if item.source_template else None
            ),
            "source_template_army_name": (
                item.source_template.army.name if item.source_template else None
            ),
            "can_update_template": bool(
                item.source_template
                and item.source_template.army_id == roster.army_id
            ),
        }
        for item in units
    ]
    total_cost = sum(row["entry_cost"] for row in unit_rows)
    return templates.TemplateResponse(
        request,
        "roster_edit.html",
        {
            "request": request,
            "user": user,
            "roster": roster,
            "units": units,
            "unit_rows": unit_rows,
            "units_payload": [
                _roster_unit_payload(item, roster)
                for item in units
            ],
            "total_cost": total_cost,
            "display_points_limit": scale_points(
                roster.points_limit, roster.points_scale
            ),
            "army_templates": roster.army.templates if roster.army else [],
            "armies": armies,
            "shield_fist_enabled": shield_fist_enabled,
            "requires_custom_stats": requires_custom_stats,
            "csrf_token": get_csrf_token(request),
        },
    )


@router.post("/{roster_id}/settings")
def update_roster_settings(
    roster_id: int,
    request: Request,
    name: str = Form(...),
    csrf_token: str = Form(...),
    points_limit: int | None = Form(default=None),
    custom_stats_enabled: bool = Form(default=False),
    points_scaling_enabled: bool = Form(default=False),
    points_scale: int = Form(default=10, ge=1, le=1_000_000),
    collapse_descriptions: bool = Form(default=False),
    small_battle_enabled: bool = Form(default=False),
    shield_fist_enabled: bool = Form(default=False),
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> RedirectResponse:
    validate_csrf(request, csrf_token)
    roster = _owned_roster(db, roster_id, user.id)
    if points_limit is not None and points_limit <= 0:
        raise HTTPException(status_code=422, detail="Limit punktów musi być dodatni")
    clean_name = _clean_name(name, "Nazwa rozpiski")
    effective_points_scale = points_scale if points_scaling_enabled else 1
    units = db.execute(
        select(models.RosterUnit).where(models.RosterUnit.roster_id == roster.id)
    ).scalars().all()
    scale_standard_toughness = (
        roster.small_battle_enabled != small_battle_enabled
        and not roster.custom_stats_enabled
        and not custom_stats_enabled
    )
    for unit in units:
        quote_request = request_from_snapshot(
            unit,
            unit_copies=unit.unit_copies,
            custom_stats_enabled=custom_stats_enabled,
            points_scale=effective_points_scale,
            small_battle_enabled=small_battle_enabled,
        )
        if scale_standard_toughness:
            factor = Decimal("2") if small_battle_enabled else Decimal("0.5")
            quote_request = quote_request.model_copy(
                update={"toughness": quote_request.toughness * factor}
            )
        try:
            quote = calculate_unit_quote(
                quote_request, ruleset_version=roster.ruleset_version
            )
        except QuoteValidationError as exc:
            raise HTTPException(
                status_code=409,
                detail="Ustawienia nie pasują do statystyk zapisanych oddziałów.",
            ) from exc
        apply_request_to_roster_unit(unit, quote_request, quote)
    roster.name = clean_name
    roster.points_limit = points_limit
    roster.custom_stats_enabled = custom_stats_enabled
    roster.points_scale = effective_points_scale
    roster.collapse_descriptions = collapse_descriptions
    roster.small_battle_enabled = small_battle_enabled
    roster.shield_fist_enabled = shield_fist_enabled
    db.commit()
    return RedirectResponse(url=f"/rosters/{roster.id}", status_code=303)


@router.post("/{roster_id}/army")
def change_roster_army(
    roster_id: int,
    request: Request,
    csrf_token: str = Form(...),
    army_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> RedirectResponse:
    validate_csrf(request, csrf_token)
    roster = _owned_roster(db, roster_id, user.id)
    if army_id is not None:
        _owned_army(db, army_id, user.id)
    roster.army_id = army_id
    db.commit()
    return RedirectResponse(url=f"/rosters/{roster.id}", status_code=303)


@router.post("/{roster_id}/duplicate")
def duplicate_roster(
    roster_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> RedirectResponse:
    validate_csrf(request, csrf_token)
    source = db.execute(
        select(models.Roster)
        .options(selectinload(models.Roster.roster_units))
        .where(models.Roster.id == roster_id, models.Roster.owner_id == user.id)
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404)
    clone = models.Roster(
        name=f"{source.name} — kopia"[:120],
        owner_id=user.id,
        army_id=source.army_id,
        points_limit=source.points_limit,
        ruleset_version=source.ruleset_version,
        custom_stats_enabled=source.custom_stats_enabled,
        points_scale=source.points_scale,
        collapse_descriptions=source.collapse_descriptions,
        small_battle_enabled=source.small_battle_enabled,
        shield_fist_enabled=source.shield_fist_enabled,
    )
    for item in source.roster_units:
        clone.roster_units.append(
            models.RosterUnit(
                source_template_id=item.source_template_id,
                name=item.name,
                models_per_unit=item.models_per_unit,
                unit_copies=item.unit_copies,
                defense=item.defense,
                toughness=item.toughness,
                passive_abilities_json=item.passive_abilities_json,
                special_abilities_json=item.special_abilities_json,
                profiles_json=item.profiles_json,
                position=item.position,
                unit_cost=item.unit_cost,
            )
        )
    db.add(clone)
    db.commit()
    return RedirectResponse(url=f"/rosters/{clone.id}", status_code=303)


@router.post("/{roster_id}/delete")
def delete_roster(
    roster_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> RedirectResponse:
    validate_csrf(request, csrf_token)
    db.delete(_owned_roster(db, roster_id, user.id))
    db.commit()
    return RedirectResponse(url="/rosters", status_code=303)


@router.post("/{roster_id}/units", dependencies=[Depends(require_csrf)])
def create_roster_unit(
    roster_id: int,
    payload: UnitQuoteInput,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> dict[str, object]:
    roster = _owned_roster(db, roster_id, user.id)
    request, quote = _calculate_for_roster(payload, roster)
    position = db.execute(
        select(func.coalesce(func.max(models.RosterUnit.position), -1)).where(
            models.RosterUnit.roster_id == roster.id
        )
    ).scalar_one() + 1
    unit = models.RosterUnit(
        roster_id=roster.id,
        name="",
        models_per_unit=1,
        unit_copies=1,
        defense=1,
        toughness=1,
        profiles_json="{}",
        position=position,
        unit_cost=0,
    )
    apply_request_to_roster_unit(unit, request, quote)
    db.add(unit)
    db.commit()
    return _roster_unit_payload(unit, roster)


@router.patch(
    "/{roster_id}/units/{unit_id}", dependencies=[Depends(require_csrf)]
)
def update_roster_unit(
    roster_id: int,
    unit_id: int,
    payload: UnitQuoteInput,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> dict[str, object]:
    unit, roster = _owned_unit_and_roster(db, roster_id, unit_id, user.id)
    request, quote = _calculate_for_roster(payload, roster)
    apply_request_to_roster_unit(unit, request, quote)
    db.commit()
    return _roster_unit_payload(unit, roster)


@router.post(
    "/{roster_id}/units/from-template", dependencies=[Depends(require_csrf)]
)
def create_unit_from_template(
    roster_id: int,
    payload: TemplateCopyPayload,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> dict[str, object]:
    roster = _owned_roster(db, roster_id, user.id)
    template = db.execute(
        select(models.UnitTemplate)
        .join(models.Army)
        .where(
            models.UnitTemplate.id == payload.template_id,
            models.Army.owner_id == user.id,
        )
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="Szablon nie istnieje")
    needs_custom = template_requires_custom_stats(template)
    if needs_custom and not roster.custom_stats_enabled:
        if not payload.enable_custom_stats:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "custom_stats_required",
                    "message": "Ten szablon wymaga włączenia dowolnych statystyk.",
                },
            )
        roster.custom_stats_enabled = True
    request = request_from_snapshot(
        template,
        unit_copies=payload.unit_copies,
        custom_stats_enabled=roster.custom_stats_enabled,
        points_scale=roster.points_scale,
        small_battle_enabled=roster.small_battle_enabled,
    )
    if roster.small_battle_enabled and not needs_custom:
        request = request.model_copy(
            update={"toughness": request.toughness * Decimal("2")}
        )
    try:
        quote = calculate_unit_quote(request, ruleset_version=roster.ruleset_version)
    except QuoteValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    position = db.execute(
        select(func.coalesce(func.max(models.RosterUnit.position), -1)).where(
            models.RosterUnit.roster_id == roster.id
        )
    ).scalar_one() + 1
    unit = models.RosterUnit(
        roster_id=roster.id,
        source_template_id=template.id,
        name="",
        models_per_unit=1,
        unit_copies=1,
        defense=1,
        toughness=1,
        profiles_json="{}",
        position=position,
        unit_cost=0,
    )
    apply_request_to_roster_unit(unit, request, quote)
    db.add(unit)
    db.commit()
    return _roster_unit_payload(unit, roster)


@router.post(
    "/{roster_id}/units/{unit_id}/duplicate",
    dependencies=[Depends(require_csrf)],
)
def duplicate_roster_unit(
    roster_id: int,
    unit_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> dict[str, object]:
    source, roster = _owned_unit_and_roster(db, roster_id, unit_id, user.id)
    insert_position = source.position + 1
    db.execute(
        update(models.RosterUnit)
        .where(
            models.RosterUnit.roster_id == roster_id,
            models.RosterUnit.position >= insert_position,
        )
        .values(position=models.RosterUnit.position + 1)
    )
    clone = models.RosterUnit(
        roster_id=roster_id,
        source_template_id=source.source_template_id,
        name=f"{source.name} — kopia"[:120],
        models_per_unit=source.models_per_unit,
        unit_copies=source.unit_copies,
        defense=source.defense,
        toughness=source.toughness,
        passive_abilities_json=source.passive_abilities_json,
        special_abilities_json=source.special_abilities_json,
        profiles_json=source.profiles_json,
        position=insert_position,
        unit_cost=source.unit_cost,
    )
    db.add(clone)
    db.commit()
    return _roster_unit_payload(clone, roster)


@router.delete(
    "/{roster_id}/units/{unit_id}",
    status_code=204,
    dependencies=[Depends(require_csrf)],
)
def delete_roster_unit(
    roster_id: int,
    unit_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> Response:
    unit, _ = _owned_unit_and_roster(db, roster_id, unit_id, user.id)
    removed_position = unit.position
    db.delete(unit)
    db.execute(
        update(models.RosterUnit)
        .where(
            models.RosterUnit.roster_id == roster_id,
            models.RosterUnit.position > removed_position,
        )
        .values(position=models.RosterUnit.position - 1)
    )
    db.commit()
    return Response(status_code=204)


@router.post("/{roster_id}/units/reorder", dependencies=[Depends(require_csrf)])
def reorder_roster_units(
    roster_id: int,
    payload: ReorderPayload,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> dict[str, object]:
    _owned_roster(db, roster_id, user.id)
    units = db.execute(
        select(models.RosterUnit).where(models.RosterUnit.roster_id == roster_id)
    ).scalars().all()
    by_id = {item.id: item for item in units}
    if len(payload.unit_ids) != len(set(payload.unit_ids)) or set(payload.unit_ids) != set(by_id):
        raise HTTPException(status_code=422, detail="Kolejność musi zawierać wszystkie oddziały raz")
    for position, item_id in enumerate(payload.unit_ids):
        by_id[item_id].position = position
    db.commit()
    return {"unit_ids": payload.unit_ids}


@router.post(
    "/{roster_id}/units/{unit_id}/save-template",
    dependencies=[Depends(require_csrf)],
)
def save_unit_as_template(
    roster_id: int,
    unit_id: int,
    payload: SaveTemplatePayload,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> dict[str, object]:
    unit, roster = _owned_unit_and_roster(db, roster_id, unit_id, user.id)
    army = _owned_army(db, payload.army_id, user.id)
    if roster.army_id != army.id:
        raise HTTPException(
            status_code=409,
            detail="Szablon można zapisać tylko do Armii bieżącej rozpiski.",
        )
    position = db.execute(
        select(func.coalesce(func.max(models.UnitTemplate.position), -1)).where(
            models.UnitTemplate.army_id == army.id
        )
    ).scalar_one() + 1
    template = create_template_from_roster_unit(
        unit,
        army=army,
        position=position,
        ruleset_version=roster.ruleset_version,
    )
    db.add(template)
    db.flush()
    unit.source_template_id = template.id
    db.commit()
    return {"template_id": template.id, "name": template.name}


@router.post(
    "/{roster_id}/units/{unit_id}/update-template",
    dependencies=[Depends(require_csrf)],
)
def update_source_template(
    roster_id: int,
    unit_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> dict[str, object]:
    unit, roster = _owned_unit_and_roster(db, roster_id, unit_id, user.id)
    if unit.source_template_id is None:
        raise HTTPException(status_code=409, detail="Oddział nie pochodzi z szablonu")
    template = db.execute(
        select(models.UnitTemplate)
        .join(models.Army)
        .where(
            models.UnitTemplate.id == unit.source_template_id,
            models.Army.owner_id == user.id,
        )
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="Szablon nie istnieje")
    if roster.army_id != template.army_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "Aby zaktualizować ten szablon, ponownie przypisz rozpisce "
                "Armię źródłową."
            ),
        )
    update_template_from_roster_unit(
        template, unit, ruleset_version=roster.ruleset_version
    )
    db.commit()
    return {"template_id": template.id, "name": template.name}
