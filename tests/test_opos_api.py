from __future__ import annotations

import json
from collections.abc import Generator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from app import models
from app.db import Base, get_db
from app.routers import armies, export, quote, rosters
from app.security import get_csrf_token


def _profile_payload(name: str = "Straż") -> dict[str, object]:
    return {
        "name": name,
        "models_per_unit": 2,
        "unit_copies": 3,
        "defense": 4,
        "toughness": 2,
        "passive_abilities": ["steadfast"],
        "special_abilities": [],
        "profiles": {
            "melee": {"dice": 1, "strength": 1, "abilities": []},
            "short": {"dice": 0, "strength": 0, "abilities": []},
            "long": {"dice": 0, "strength": 0, "abilities": []},
        },
        "custom_stats_enabled": False,
    }


@pytest.fixture()
def api() -> Generator[tuple[TestClient, sessionmaker, dict[str, int], list[int]], None, None]:
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    sessions = sessionmaker(bind=test_engine, expire_on_commit=False)
    with sessions.begin() as session:
        owner = models.User(username="owner", password_hash="hash")
        stranger = models.User(username="stranger", password_hash="hash")
        session.add_all([owner, stranger])
        session.flush()
        army = models.Army(name="Moja", owner_id=owner.id)
        second_army = models.Army(name="Druga", owner_id=owner.id)
        foreign_army = models.Army(name="Cudza", owner_id=stranger.id)
        roster = models.Roster(
            name="Test",
            owner_id=owner.id,
            army=army,
            ruleset_version="v3",
            points_scale=1,
        )
        foreign_roster = models.Roster(
            name="Cudza",
            owner_id=stranger.id,
            army=foreign_army,
            ruleset_version="v3",
            points_scale=1,
        )
        session.add_all([roster, second_army, foreign_roster])
        session.flush()
        ids = {
            "owner": owner.id,
            "army": army.id,
            "second_army": second_army.id,
            "foreign_army": foreign_army.id,
            "roster": roster.id,
            "foreign_roster": foreign_roster.id,
        }

    current_user = models.User(
        id=ids["owner"],
        username="owner",
        password_hash="hash",
        default_custom_stats_enabled=False,
        default_points_scale=10,
        default_collapse_descriptions=False,
        default_small_battle_enabled=False,
        default_shield_fist_enabled=False,
    )

    def db_override() -> Generator[Session, None, None]:
        with sessions() as session:
            yield session

    def user_override() -> models.User:
        return current_user

    test_app = FastAPI()
    test_app.add_middleware(SessionMiddleware, secret_key="test-secret")
    test_app.mount("/static", StaticFiles(directory="app/static"), name="static")
    test_app.include_router(quote.router)
    test_app.include_router(armies.router)
    test_app.include_router(rosters.router)
    test_app.include_router(export.router)
    test_app.dependency_overrides[get_db] = db_override
    test_app.dependency_overrides[armies.current_user_dep] = user_override
    test_app.dependency_overrides[rosters.current_user_dep] = user_override
    test_app.dependency_overrides[export.current_user_dep] = user_override

    @test_app.get("/_csrf")
    def csrf(request: Request) -> dict[str, str]:
        return {"token": get_csrf_token(request)}

    queries: list[int] = []

    @event.listens_for(test_engine, "before_cursor_execute")
    def count_query(*args: object, **kwargs: object) -> None:
        del args, kwargs
        queries.append(1)

    with TestClient(test_app) as client:
        yield client, sessions, ids, queries


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.get("/_csrf").json()["token"]}


def test_quote_is_stateless_and_does_not_query_database(api) -> None:
    client, _, _, queries = api
    queries.clear()

    response = client.post("/quote", json=_profile_payload())

    assert response.status_code == 200
    assert response.json()["entry_cost"] == "222"
    assert queries == []


def test_create_roster_uses_numeric_scale_and_disables_small_battle_by_default(api) -> None:
    client, sessions, _, _ = api
    token = client.get("/_csrf").json()["token"]

    form = client.get("/rosters/new")
    created = client.post(
        "/rosters",
        data={
            "name": "Mała rozpiska",
            "points_limit": "505",
            "csrf_token": token,
            "custom_stats_enabled": "true",
            "points_scaling_enabled": "true",
            "points_scale": "7",
            "collapse_descriptions": "true",
        },
        follow_redirects=False,
    )

    assert form.status_code == 200
    assert '<details class="additional-settings">' in form.text
    assert '<details class="additional-settings" open>' not in form.text
    assert 'name="points_scaling_enabled" type="checkbox" value="true" checked' in form.text
    assert 'name="points_scale" type="number"' in form.text
    assert '<span class="points-limit-label">Limit punktów, bez skalowania</span>' in form.text
    assert "W podsumowaniu zostanie podzielony przez skalowanie." not in form.text
    assert 'name="collapse_descriptions"' in form.text
    assert 'name="small_battle_enabled"' in form.text
    assert 'name="shield_fist_enabled"' in form.text
    assert 'name="save_as_defaults"' in form.text
    assert 'name="points_scale" type="number" min="1" max="1000000" step="1" value="10"' in form.text
    assert 'name="small_battle_enabled" type="checkbox" value="true" checked' not in form.text
    assert created.status_code == 303
    with sessions() as session:
        roster = session.query(models.Roster).filter_by(name="Mała rozpiska").one()
        assert roster.points_limit == 505
        assert roster.custom_stats_enabled is True
        assert roster.points_scale == 7
        assert roster.collapse_descriptions is True
        assert roster.small_battle_enabled is False
        assert roster.shield_fist_enabled is False


def test_new_roster_settings_can_be_saved_as_user_defaults(api) -> None:
    client, sessions, ids, _ = api
    token = client.get("/_csrf").json()["token"]

    response = client.post(
        "/rosters",
        data={
            "name": "Domyślna",
            "csrf_token": token,
            "custom_stats_enabled": "true",
            "points_scaling_enabled": "true",
            "points_scale": "7",
            "collapse_descriptions": "true",
            "small_battle_enabled": "true",
            "shield_fist_enabled": "true",
            "save_as_defaults": "true",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with sessions() as session:
        user = session.get(models.User, ids["owner"])
        assert user.default_custom_stats_enabled is True
        assert user.default_points_scale == 7
        assert user.default_collapse_descriptions is True
        assert user.default_small_battle_enabled is True
        assert user.default_shield_fist_enabled is True
        roster = session.query(models.Roster).filter_by(name="Domyślna").one()
        assert roster.shield_fist_enabled is True

    current_user = client.app.dependency_overrides[rosters.current_user_dep]()
    current_user.default_custom_stats_enabled = True
    current_user.default_points_scale = 7
    current_user.default_collapse_descriptions = True
    current_user.default_small_battle_enabled = True
    current_user.default_shield_fist_enabled = True
    form = client.get("/rosters/new")
    assert 'name="points_scale" type="number" min="1" max="1000000" step="1" value="7"' in form.text
    assert 'name="shield_fist_enabled" type="checkbox" value="true" checked' in form.text
    assert 'name="save_as_defaults" type="checkbox" value="true" checked' not in form.text


def test_unchecked_points_scaling_persists_base_scale_one(api) -> None:
    client, sessions, _, _ = api
    token = client.get("/_csrf").json()["token"]

    response = client.post(
        "/rosters",
        data={
            "name": "Bez skalowania",
            "csrf_token": token,
            "points_scale": "7",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with sessions() as session:
        roster = session.query(models.Roster).filter_by(name="Bez skalowania").one()
        assert roster.points_scale == 1


def test_write_recalculates_price_and_rejects_client_price(api) -> None:
    client, sessions, ids, _ = api
    headers = _csrf(client)
    stale = {**_profile_payload(), "unit_cost": 1}

    rejected = client.post(
        f"/rosters/{ids['roster']}/units", json=stale, headers=headers
    )
    accepted = client.post(
        f"/rosters/{ids['roster']}/units",
        json=_profile_payload(),
        headers=headers,
    )

    assert rejected.status_code == 422
    assert accepted.status_code == 200
    assert accepted.json()["unit_cost"] == 74
    assert accepted.json()["entry_cost"] == 222
    with sessions() as session:
        stored = session.get(models.RosterUnit, accepted.json()["id"])
        assert stored is not None and stored.unit_cost == 74


def test_scaled_roster_returns_scaled_cost_but_persists_base_cost(api) -> None:
    client, sessions, ids, _ = api
    with sessions.begin() as session:
        session.get(models.Roster, ids["roster"]).points_scale = 10

    response = client.post(
        f"/rosters/{ids['roster']}/units",
        json=_profile_payload(),
        headers=_csrf(client),
    )

    assert response.status_code == 200
    assert response.json()["unit_cost"] == 7
    assert response.json()["entry_cost"] == 21
    with sessions() as session:
        stored = session.get(models.RosterUnit, response.json()["id"])
        assert stored is not None and stored.unit_cost == 74


def test_mutations_require_csrf_and_hide_foreign_resources(api) -> None:
    client, _, ids, _ = api
    no_csrf = client.post(
        f"/rosters/{ids['roster']}/units", json=_profile_payload()
    )
    foreign = client.post(
        f"/rosters/{ids['foreign_roster']}/units",
        json=_profile_payload(),
        headers=_csrf(client),
    )
    foreign_army = client.post(
        f"/armies/{ids['foreign_army']}/templates",
        json=_profile_payload(),
        headers=_csrf(client),
    )

    assert no_csrf.status_code == 403
    assert foreign.status_code == 404
    assert foreign_army.status_code == 404


def test_roster_cannot_be_reassigned_or_saved_to_foreign_army(api) -> None:
    client, sessions, ids, _ = api
    token = client.get("/_csrf").json()["token"]
    headers = {"X-CSRF-Token": token}
    created = client.post(
        f"/rosters/{ids['roster']}/units",
        json=_profile_payload(),
        headers=headers,
    ).json()

    reassigned = client.post(
        f"/rosters/{ids['roster']}/army",
        data={
            "csrf_token": token,
            "army_id": str(ids["foreign_army"]),
        },
        follow_redirects=False,
    )
    saved = client.post(
        f"/rosters/{ids['roster']}/units/{created['id']}/save-template",
        json={"army_id": ids["foreign_army"]},
        headers=headers,
    )

    assert reassigned.status_code == 404
    assert saved.status_code == 404
    with sessions() as session:
        assert session.get(models.Roster, ids["roster"]).army_id == ids["army"]


def test_roster_ignores_client_attempt_to_enable_shield_fist_mode(api) -> None:
    client, _, ids, _ = api
    payload = _profile_payload()
    payload["shield_fist_enabled"] = True
    payload["defense"] = 0

    response = client.post(
        f"/rosters/{ids['roster']}/units",
        json=payload,
        headers=_csrf(client),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Zbroja must be positive"


def test_template_copy_does_not_propagate_until_explicit_update(api) -> None:
    client, sessions, ids, _ = api
    headers = _csrf(client)
    created = client.post(
        f"/rosters/{ids['roster']}/units",
        json=_profile_payload(),
        headers=headers,
    ).json()
    saved = client.post(
        f"/rosters/{ids['roster']}/units/{created['id']}/save-template",
        json={"army_id": ids["army"]},
        headers=headers,
    ).json()

    client.patch(
        f"/rosters/{ids['roster']}/units/{created['id']}",
        json=_profile_payload(name="Zmieniona"),
        headers=headers,
    )
    with sessions() as session:
        template = session.get(models.UnitTemplate, saved["template_id"])
        assert template is not None and template.name == "Straż"

    client.post(
        f"/rosters/{ids['roster']}/units/{created['id']}/update-template",
        headers=headers,
    )
    with sessions() as session:
        template = session.get(models.UnitTemplate, saved["template_id"])
        assert template is not None and template.name == "Zmieniona"


def test_changing_roster_army_preserves_and_conditionally_unlocks_source(api) -> None:
    client, sessions, ids, _ = api
    headers = _csrf(client)
    created = client.post(
        f"/rosters/{ids['roster']}/units",
        json=_profile_payload(),
        headers=headers,
    ).json()
    original = client.post(
        f"/rosters/{ids['roster']}/units/{created['id']}/save-template",
        json={"army_id": ids["army"]},
        headers=headers,
    ).json()

    def change_army(army_id: int) -> None:
        response = client.post(
            f"/rosters/{ids['roster']}/army",
            data={
                "csrf_token": headers["X-CSRF-Token"],
                "army_id": str(army_id),
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    change_army(ids["second_army"])
    with sessions() as session:
        unit = session.get(models.RosterUnit, created["id"])
        assert unit.source_template_id == original["template_id"]
    detail = client.get(f"/rosters/{ids['roster']}")
    assert "Przypisz ją ponownie rozpisce" in detail.text
    assert 'class="button js-update-template" type="button" disabled' in detail.text
    blocked = client.post(
        f"/rosters/{ids['roster']}/units/{created['id']}/update-template",
        headers=headers,
    )
    assert blocked.status_code == 409

    change_army(ids["army"])
    detail = client.get(f"/rosters/{ids['roster']}")
    assert 'class="button js-update-template" type="button" disabled' not in detail.text
    assert client.post(
        f"/rosters/{ids['roster']}/units/{created['id']}/update-template",
        headers=headers,
    ).status_code == 200

    change_army(ids["second_army"])
    rebound = client.post(
        f"/rosters/{ids['roster']}/units/{created['id']}/save-template",
        json={"army_id": ids["second_army"]},
        headers=headers,
    )
    assert rebound.status_code == 200
    with sessions() as session:
        unit = session.get(models.RosterUnit, created["id"])
        template = session.get(models.UnitTemplate, unit.source_template_id)
        assert template.army_id == ids["second_army"]
        assert unit.source_template_id != original["template_id"]


def test_shield_and_fist_is_display_only_and_storage_stays_canonical(api) -> None:
    client, sessions, ids, _ = api
    with sessions.begin() as session:
        session.get(models.Roster, ids["roster"]).shield_fist_enabled = True
    payload = _profile_payload()
    payload["defense"] = 1
    payload["profiles"] = {
        "melee": {"dice": 1, "strength": 2, "abilities": []},
        "short": {"dice": 0, "strength": 3, "abilities": []},
        "long": {"dice": 0, "strength": 3, "abilities": []},
    }
    response = client.post(
        f"/rosters/{ids['roster']}/units",
        json=payload,
        headers=_csrf(client),
    )

    assert response.status_code == 200
    with sessions() as session:
        unit = session.get(models.RosterUnit, response.json()["id"])
        profiles = json.loads(unit.profiles_json)
        assert unit.defense == 4
        assert profiles["melee"]["strength"] == "1"
    detail = client.get(f"/rosters/{ids['roster']}")
    assert 'aria-label="Tarcza +1"' in detail.text
    assert 'aria-label="Pięść 2+"' in detail.text


def test_v3_ruleset_manifest_transforms_shield_fist_values(api) -> None:
    client, _, _, _ = api

    manifest = client.get("/ruleset?shield_fist_enabled=true").json()

    assert manifest["stat_labels"] == {
        "defense": "Tarcza",
        "toughness": "Życie",
        "strength": "Pięść",
    }
    assert manifest["standard_stats"]["defense"] == ["0", "1", "2"]
    assert manifest["standard_stats"]["strength"] == ["3", "2", "1"]
    assert manifest["custom_stats"]["defense"] == {
        "minimum": "-2",
        "maximum": "3",
        "integer_only": True,
    }


def test_custom_template_requires_confirmation_and_enables_roster_mode(api) -> None:
    client, sessions, ids, _ = api
    custom_profiles = _profile_payload()
    with sessions.begin() as session:
        template = models.UnitTemplate(
            army_id=ids["army"],
            owner_id=ids["owner"],
            name="Niestandardowy",
            models_per_unit=1,
            defense=6,
            toughness=99,
            passive_abilities_json="[]",
            special_abilities_json="[]",
            profiles_json=json.dumps(custom_profiles["profiles"]),
            ruleset_version="v3",
            position=0,
        )
        session.add(template)
        session.flush()
        template_id = template.id
    headers = _csrf(client)

    prompt = client.post(
        f"/rosters/{ids['roster']}/units/from-template",
        json={"template_id": template_id},
        headers=headers,
    )
    accepted = client.post(
        f"/rosters/{ids['roster']}/units/from-template",
        json={"template_id": template_id, "enable_custom_stats": True},
        headers=headers,
    )

    assert prompt.status_code == 409
    assert accepted.status_code == 200
    with sessions() as session:
        assert session.get(models.Roster, ids["roster"]).custom_stats_enabled is True


def test_cards_view_uses_two_queries_and_shows_model_count(api) -> None:
    client, _, ids, queries = api
    client.post(
        f"/rosters/{ids['roster']}/units",
        json=_profile_payload(),
        headers=_csrf(client),
    )
    queries.clear()

    response = client.get(f"/rosters/{ids['roster']}/cards")

    assert response.status_code == 200
    assert len(queries) == 2
    assert response.text.count('class="unit-card unit-card-profile') == 1
    assert 'aria-label="Liczebność 2"' in response.text
    assert "unit_copies" not in response.text


def test_cards_keep_attack_descriptions_below_profiles_only_when_expanded(api) -> None:
    client, sessions, ids, _ = api
    payload = _profile_payload()
    payload["profiles"]["short"]["dice"] = 1
    payload["profiles"]["short"]["abilities"] = ["double"]
    client.post(
        f"/rosters/{ids['roster']}/units",
        json=payload,
        headers=_csrf(client),
    )

    expanded = client.get(f"/rosters/{ids['roster']}/cards")

    assert expanded.status_code == 200
    assert 'class="card-attack-descriptions"' in expanded.text
    assert "Każdy sukces liczy się również jako remis." in expanded.text
    assert 'class="card-abilities is-separated"' in expanded.text

    with sessions.begin() as session:
        session.get(models.Roster, ids["roster"]).collapse_descriptions = True
    collapsed = client.get(f"/rosters/{ids['roster']}/cards")

    assert collapsed.status_code == 200
    assert "Każdy sukces liczy się również jako remis." not in collapsed.text
    assert 'aria-label="Opisy zdolności ataku"' not in collapsed.text
    assert "Podwójny (Krótki)" not in collapsed.text
    assert "Podwójny" in collapsed.text
    assert 'class="card-abilities is-separated"' not in collapsed.text


def test_roster_detail_renders_icons_after_unit_is_saved(api) -> None:
    client, _, ids, _ = api
    created = client.post(
        f"/rosters/{ids['roster']}/units",
        json=_profile_payload(),
        headers=_csrf(client),
    ).json()
    client.post(
        f"/rosters/{ids['roster']}/units/{created['id']}/save-template",
        json={"army_id": ids["army"]},
        headers=_csrf(client),
    )

    response = client.get(f"/rosters/{ids['roster']}")

    assert response.status_code == 200
    assert "Straż" in response.text
    assert "/static/icons/opos.svg#icon-defense" in response.text
    assert 'aria-label="Zbroja 4"' in response.text
    assert 'aria-label="Zbroja 4.00"' not in response.text
    assert 'aria-label="Życie 2"' in response.text
    assert "/static/icons/opos.svg#icon-models" in response.text
    assert 'aria-label="Liczebność 2"' in response.text
    assert response.text.count('data-range="') == 3
    assert "Wręcz" in response.text
    assert "Krótki" in response.text
    assert "Daleki" in response.text
    assert 'class="drag-handle"' in response.text
    assert "js-move-up" not in response.text
    assert "js-move-down" not in response.text
    assert response.text.count('class="editor-section') == 3
    assert 'class="library-tools"' in response.text
    assert 'aria-label="Zdolności oddziału"' in response.text
    assert "/static/icons/opos.svg#icon-steadfast" in response.text
    assert 'name="points_scale"' in response.text
    assert 'name="points_scaling_enabled"' in response.text
    assert '<span class="points-limit-label">Limit punktów</span>' in response.text
    assert "W podsumowaniu zostanie podzielony przez skalowanie." not in response.text
    assert 'name="collapse_descriptions"' in response.text
    assert 'name="small_battle_enabled"' in response.text
    assert 'name="shield_fist_enabled"' in response.text
    assert f'action="/rosters/{ids["roster"]}/army"' in response.text
    assert 'id="library-title">Dodaj z armii' in response.text
    assert 'id="roster-army-select" name="army_id"' in response.text
    assert "Edytuj armię" not in response.text
    assert 'class="template-delete js-delete-template"' in response.text
    assert f'data-army-id="{ids["army"]}"' in response.text


def test_roster_and_cards_keep_two_query_budget_for_twelve_profiles(api) -> None:
    client, sessions, ids, queries = api
    profiles_json = json.dumps(_profile_payload()["profiles"])
    with sessions.begin() as session:
        session.add_all(
            [
                models.RosterUnit(
                    roster_id=ids["roster"],
                    name=f"Profil {position + 1}",
                    models_per_unit=3,
                    unit_copies=25,
                    defense=4,
                    toughness=3,
                    passive_abilities_json="[]",
                    special_abilities_json="[]",
                    profiles_json=profiles_json,
                    position=position,
                    unit_cost=100 + position,
                )
                for position in range(12)
            ]
        )

    queries.clear()
    detail = client.get(f"/rosters/{ids['roster']}")
    detail_queries = len(queries)

    queries.clear()
    cards = client.get(f"/rosters/{ids['roster']}/cards")
    card_queries = len(queries)

    assert detail.status_code == 200
    assert cards.status_code == 200
    assert detail_queries == 2
    assert card_queries == 2
    assert detail.text.count('class="unit-row"') == 12
    assert cards.text.count('class="unit-card unit-card-profile') == 12
    assert "× 25" in detail.text
    assert "× 25" not in cards.text


def test_custom_stats_cannot_be_disabled_while_custom_units_exist(api) -> None:
    client, sessions, ids, _ = api
    with sessions.begin() as session:
        session.get(models.Roster, ids["roster"]).custom_stats_enabled = True
    custom = _profile_payload()
    custom.update(
        defense=6,
        toughness=99,
        custom_stats_enabled=True,
    )
    custom["profiles"] = {
        "melee": {"dice": 1, "strength": 4, "abilities": []},
        "short": {"dice": 0, "strength": 0, "abilities": []},
        "long": {"dice": 0, "strength": 0, "abilities": []},
    }
    headers = _csrf(client)
    assert client.post(
        f"/rosters/{ids['roster']}/units", json=custom, headers=headers
    ).status_code == 200

    detail = client.get(f"/rosters/{ids['roster']}")
    assert 'data-requires-custom-stats="true"' in detail.text

    response = client.post(
        f"/rosters/{ids['roster']}/settings",
        data={
            "name": "Test",
            "csrf_token": headers["X-CSRF-Token"],
            "shield_fist_enabled": "true",
        },
    )

    assert response.status_code == 409
    with sessions() as session:
        roster = session.get(models.Roster, ids["roster"])
        assert roster.custom_stats_enabled is True
        assert roster.shield_fist_enabled is False


def test_roster_modes_recalculate_points_and_scale_standard_toughness(api) -> None:
    client, sessions, ids, _ = api
    headers = _csrf(client)
    created = client.post(
        f"/rosters/{ids['roster']}/units",
        json=_profile_payload(),
        headers=headers,
    ).json()

    with sessions.begin() as session:
        session.get(models.Roster, ids["roster"]).points_limit = 500

    response = client.post(
        f"/rosters/{ids['roster']}/settings",
        data={
            "name": "Test",
            "csrf_token": headers["X-CSRF-Token"],
            "points_limit": "500",
            "points_scaling_enabled": "true",
            "points_scale": "10",
            "collapse_descriptions": "true",
            "small_battle_enabled": "true",
            "shield_fist_enabled": "true",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with sessions() as session:
        roster = session.get(models.Roster, ids["roster"])
        unit = session.get(models.RosterUnit, created["id"])
        assert roster.points_scale == 10
        assert roster.collapse_descriptions is True
        assert roster.small_battle_enabled is True
        assert roster.shield_fist_enabled is True
        assert roster.points_limit == 500
        assert unit.toughness == 4
        assert unit.unit_cost > 13


def test_collapsed_cards_hide_ability_descriptions(api) -> None:
    client, sessions, ids, _ = api
    client.post(
        f"/rosters/{ids['roster']}/units",
        json=_profile_payload(),
        headers=_csrf(client),
    )
    with sessions.begin() as session:
        session.get(models.Roster, ids["roster"]).collapse_descriptions = True

    response = client.get(f"/rosters/{ids['roster']}/cards")

    assert response.status_code == 200
    assert 'unit-card-profile is-compact' not in response.text
    assert 'class="attack-primary"' in response.text
    assert 'class="attack-range"' not in response.text
    assert "Wytrwały" in response.text
    assert "+1 do obrony za każdy znacznik aktywacji." not in response.text
