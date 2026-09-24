"""Unit identification survives persistence, copying, upgrades and printing."""

import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app import models
from app.db import Base, upgrade_opos_database
from app.services import db_restore
from app.services.cards import build_unit_cards
from app.services.icon_sprite import render_card_icon
from app.services.unit_emblems import UNIT_EMBLEMS
from test_opos_api import _csrf, _profile_payload, api  # noqa: F401
from test_opos_cards import _unit


@pytest.mark.parametrize("emblem", UNIT_EMBLEMS)
def test_emblem_roundtrip_quote_and_inline_card(api, emblem):
    client, sessions, ids, queries = api
    payload = {**_profile_payload(), "emblem": emblem}
    baseline = client.post("/quote", json=_profile_payload()).json()
    queries.clear()
    quoted = client.post("/quote", json=payload)
    assert quoted.json() == baseline
    assert queries == []
    response = client.post(
        f"/rosters/{ids['roster']}/units", json=payload, headers=_csrf(client)
    )
    assert response.status_code == 200
    assert response.json()["emblem"] == emblem
    with sessions() as session:
        assert session.get(models.RosterUnit, response.json()["id"]).emblem == emblem
    queries.clear()
    html = client.get(f"/rosters/{ids['roster']}")
    assert html.status_code == 200
    assert len(queries) <= 2
    assert f"#icon-emblem-{emblem}" in html.text
    queries.clear()
    cards = client.get(f"/rosters/{ids['roster']}/cards")
    assert cards.status_code == 200
    assert len(queries) <= 2
    svg = str(render_card_icon(f"emblem-{emblem}"))
    ET.fromstring(svg)
    assert svg in cards.text
    assert "<use" not in svg
    assert "href=" not in svg


@pytest.mark.parametrize("emblem", ["unknown", "../sword", "<script>", "https://bad.test/a", ""])
def test_unknown_emblem_is_rejected_without_persisting(api, emblem):
    client, sessions, ids, _ = api
    payload = {**_profile_payload(), "emblem": emblem}
    assert client.post("/quote", json=payload).status_code == 422
    assert client.post(
        f"/rosters/{ids['roster']}/units", json=payload, headers=_csrf(client)
    ).status_code == 422
    with sessions() as session:
        assert session.scalars(select(models.RosterUnit)).all() == []


def test_emblem_copies_independently_and_can_be_cleared(api):
    client, sessions, ids, _ = api
    headers = _csrf(client)
    base = f"/rosters/{ids['roster']}"
    payload = {**_profile_payload(), "emblem": "sword"}
    created = client.post(f"{base}/units", json=payload, headers=headers).json()
    url = f"{base}/units/{created['id']}"
    duplicated = client.post(f"{url}/duplicate", headers=headers)
    assert duplicated.json()["emblem"] == "sword"
    saved = client.post(f"{url}/save-template", json={"army_id": ids["army"]}, headers=headers)
    assert saved.status_code == 200
    with sessions() as session:
        template_id = session.get(models.RosterUnit, created["id"]).source_template_id
    copied = client.post(f"{base}/units/from-template", json={"template_id": template_id}, headers=headers)
    assert copied.json()["emblem"] == "sword"
    changed = client.patch(url, json={**payload, "emblem": "flame"}, headers=headers)
    assert changed.json()["emblem"] == "flame"
    with sessions() as session:
        assert session.get(models.UnitTemplate, template_id).emblem == "sword"
        assert session.get(models.RosterUnit, copied.json()["id"]).emblem == "sword"
    assert client.post(f"{url}/update-template", headers=headers).status_code == 200
    with sessions() as session:
        assert session.get(models.UnitTemplate, template_id).emblem == "flame"
    cloned = client.post(
        f"{base}/duplicate", data={"csrf_token": headers["X-CSRF-Token"]}, follow_redirects=False
    )
    assert cloned.status_code == 303
    assert "#icon-emblem-flame" in client.get(cloned.headers["location"]).text
    cleared = client.patch(url, json={**payload, "emblem": None}, headers=headers)
    assert cleared.json()["emblem"] is None
    legacy = client.post(f"{base}/units", json=_profile_payload(), headers=headers)
    assert legacy.json()["emblem"] is None
    assert client.patch(
        f"/armies/{ids['army']}/templates/{template_id}",
        json={**payload, "emblem": "medical"}, headers=headers,
    ).status_code == 200
    assert "#icon-emblem-medical" in client.get(f"/armies/{ids['army']}").text


@pytest.mark.parametrize("restore", [False, True])
def test_old_database_gains_nullable_emblems_idempotently(tmp_path: Path, restore):
    path = tmp_path / "old-opos.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        owner = models.User(username="owner", password_hash="hash")
        roster = models.Roster(name="Zachowana rozpiska", owner=owner)
        unit = _unit()
        roster.roster_units.append(unit)
        session.add(roster)
        session.commit()
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA user_version = 30100")
        for table in ("unit_templates", "roster_units"):
            connection.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN emblem")
    for _ in range(2):
        if restore:
            db_restore._validate_sqlite_file(path)
            db_restore._upgrade_sqlite_file(path)
        else:
            upgrade_opos_database(engine)
    for table in ("unit_templates", "roster_units"):
        columns = {c["name"]: c for c in inspect(engine).get_columns(table)}
        assert columns["emblem"]["nullable"] is True
    with Session(engine) as session:
        unit = session.scalars(select(models.RosterUnit)).one()
        assert unit.name == "Gwardia"
        assert unit.unit_cost == 83
        assert unit.emblem is None
        assert unit.roster.name == "Zachowana rozpiska"
    engine.dispose()


def test_continuation_cards_retain_the_same_emblem():
    unit = _unit()
    unit.emblem = "mech"
    unit.passive_abilities_json = json.dumps([
        "hero", "ambush", "agile", "fast", "jump", "dodge", "parry", "steadfast",
    ])
    cards = build_unit_cards(unit, ruleset_version="v3")
    assert len(cards) > 1
    assert all(card["emblem"] == "mech" for card in cards)


def test_long_title_reserves_space_without_losing_abilities():
    unit = _unit()
    unit.emblem = "mech"
    unit.passive_abilities_json = json.dumps([
        "hero", "ambush", "agile", "fast", "jump", "dodge", "parry", "steadfast",
    ])
    short_cards = build_unit_cards(unit, ruleset_version="v3")
    unit.name = "Bardzo długa nazwa oddziału wymagająca zawinięcia nagłówka karty"
    long_cards = build_unit_cards(unit, ruleset_version="v3")
    assert len(long_cards[0]["abilities"]) == len(short_cards[0]["abilities"]) - 2
    assert [a for c in long_cards for a in c["abilities"]] == [
        a for c in short_cards for a in c["abilities"]
    ]
