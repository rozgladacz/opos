import json
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app import models
from app.db import (
    Base,
    assert_not_legacy_szop_database,
    ensure_roster_mode_columns,
    ensure_user_preference_columns,
    upgrade_opos_database,
)
from app.services.opos_rules import QuoteValidationError, calculate_unit_quote
from app.services.opos_units import OPOS_V3_1_USER_VERSION, request_from_snapshot


def _profiles() -> str:
    return json.dumps(
        {
            "melee": {"dice": 1, "strength": 0, "abilities": []},
            "short": {"dice": 1, "strength": 0, "abilities": []},
            "long": {"dice": 1, "strength": 0, "abilities": []},
        }
    )


def test_fresh_schema_contains_only_opos_domain_tables() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)

    assert set(inspect(test_engine).get_table_names()) == {
        "users", "armies", "unit_templates", "rosters", "roster_units",
    }
    inspector = inspect(test_engine)
    army_columns = {item["name"] for item in inspector.get_columns("armies")}
    roster_columns = {item["name"] for item in inspector.get_columns("rosters")}
    user_columns = {item["name"] for item in inspector.get_columns("users")}
    assert "shield_fist_enabled" not in army_columns
    assert "shield_fist_enabled" in roster_columns
    assert {
        "default_custom_stats_enabled",
        "default_points_scale",
        "default_collapse_descriptions",
        "default_small_battle_enabled",
        "default_shield_fist_enabled",
    } <= user_columns


def test_roster_cost_uses_rounded_unit_cost_times_copies() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        user = models.User(username="test", password_hash="hash")
        roster = models.Roster(name="Test", owner=user)
        roster.roster_units = [
            models.RosterUnit(
                name="Straż",
                models_per_unit=3,
                unit_copies=4,
                defense=Decimal("4"),
                toughness=Decimal("2"),
                profiles_json="{}",
                unit_cost=37,
                position=0,
            )
        ]
        session.add(roster)
        session.flush()

        assert roster.roster_units[0].entry_cost == 148
        assert roster.total_cost == 148


def test_required_foreign_key_and_position_indexes_exist() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    inspector = inspect(test_engine)

    assert "ix_armies_owner_id" in {item["name"] for item in inspector.get_indexes("armies")}
    assert "ix_rosters_owner_id" in {item["name"] for item in inspector.get_indexes("rosters")}
    assert "ix_rosters_army_id" in {item["name"] for item in inspector.get_indexes("rosters")}
    assert "ix_unit_templates_army_position" in {
        item["name"] for item in inspector.get_indexes("unit_templates")
    }
    assert "ix_roster_units_roster_position" in {
        item["name"] for item in inspector.get_indexes("roster_units")
    }


def test_legacy_szop_database_is_rejected_before_opos_bootstrap() -> None:
    legacy_engine = create_engine("sqlite:///:memory:")
    with legacy_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE armories (id INTEGER PRIMARY KEY)")

    try:
        assert_not_legacy_szop_database(legacy_engine)
    except RuntimeError as exc:
        assert "świeżej bazy data/opos.db" in str(exc)
        assert "armories" in str(exc)
    else:  # pragma: no cover - explicit failure message
        raise AssertionError("Stara baza SZOP powinna zostać odrzucona")


def test_existing_opos_database_passes_legacy_guard() -> None:
    opos_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(opos_engine)

    assert_not_legacy_szop_database(opos_engine)


def test_existing_opos_database_gets_missing_roster_mode_columns() -> None:
    old_engine = create_engine("sqlite:///:memory:")
    with old_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE rosters (id INTEGER PRIMARY KEY, name VARCHAR(120))"
        )

    ensure_roster_mode_columns(old_engine)

    columns = {item["name"] for item in inspect(old_engine).get_columns("rosters")}
    assert {
        "points_scale",
        "collapse_descriptions",
        "small_battle_enabled",
        "shield_fist_enabled",
    } <= columns


def test_existing_opos_database_gets_user_preference_columns() -> None:
    old_engine = create_engine("sqlite:///:memory:")
    with old_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64))"
        )

    ensure_user_preference_columns(old_engine)

    columns = {item["name"] for item in inspect(old_engine).get_columns("users")}
    assert {
        "default_custom_stats_enabled",
        "default_points_scale",
        "default_collapse_descriptions",
        "default_small_battle_enabled",
        "default_shield_fist_enabled",
    } <= columns


def test_v3_1_migration_moves_shield_fist_from_army_to_roster() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    with test_engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE armies ADD COLUMN shield_fist_enabled "
            "BOOLEAN NOT NULL DEFAULT 0"
        )
    with Session(test_engine) as session:
        user = models.User(username="owner-v3-1", password_hash="hash")
        army = models.Army(name="Armia", owner=user)
        roster = models.Roster(name="Rozpiska", owner=user, army=army)
        session.add(roster)
        session.commit()
        session.execute(
            text("UPDATE armies SET shield_fist_enabled = 1 WHERE id = :id"),
            {"id": army.id},
        )
        session.execute(text("PRAGMA user_version = 30000"))
        session.commit()

    assert upgrade_opos_database(test_engine) == 1

    with Session(test_engine) as session:
        assert session.query(models.Roster).one().shield_fist_enabled is True
        assert session.execute(text("PRAGMA user_version")).scalar_one() == (
            OPOS_V3_1_USER_VERSION
        )
    assert "shield_fist_enabled" not in {
        item["name"] for item in inspect(test_engine).get_columns("armies")
    }


def test_legacy_simple_points_are_restored_to_base_values() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    with test_engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE rosters ADD COLUMN simple_points_enabled "
            "BOOLEAN NOT NULL DEFAULT 0"
        )
    with Session(test_engine) as session:
        user = models.User(username="legacy", password_hash="hash")
        roster = models.Roster(
            name="Skalowana",
            owner=user,
            points_limit=50,
            points_scale=10,
            ruleset_version="v1",
        )
        roster.roster_units.append(
            models.RosterUnit(
                name="Straż",
                models_per_unit=1,
                unit_copies=2,
                defense=3,
                toughness=2,
                passive_abilities_json="[]",
                special_abilities_json="[]",
                profiles_json=_profiles(),
                position=0,
                unit_cost=13,
            )
        )
        session.add(roster)
        session.commit()
        session.execute(
            text(
                "UPDATE rosters SET simple_points_enabled = 1 WHERE id = :id"
            ),
            {"id": roster.id},
        )
        session.execute(text("PRAGMA user_version = 10200"))
        session.commit()

    assert upgrade_opos_database(test_engine) == 2

    with Session(test_engine) as session:
        roster = session.query(models.Roster).one()
        unit = session.query(models.RosterUnit).one()
        request = request_from_snapshot(
            unit,
            unit_copies=unit.unit_copies,
            custom_stats_enabled=False,
        )
        expected = calculate_unit_quote(request, ruleset_version="v3")
        assert roster.points_scale == 10
        assert roster.points_limit == 500
        assert unit.unit_cost == int(expected.unscaled_unit_cost)
        assert unit.unit_cost > 13
        assert "simple_points_enabled" not in {
            column["name"]
            for column in inspect(test_engine).get_columns("rosters")
        }


def test_opos_1_2_migration_scales_normalizes_and_requotes_atomically() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        user = models.User(username="owner", password_hash="hash")
        army = models.Army(name="Armia", owner=user)
        template = models.UnitTemplate(
            army=army,
            owner=user,
            name="Samolot wzorcowy",
            models_per_unit=1,
            defense=3,
            toughness=1,
            passive_abilities_json='["guardian","airplane"]',
            special_abilities_json='[{"slug":"aura","target_slug":"guardian"}]',
            profiles_json=_profiles(),
            ruleset_version="v1",
            position=0,
        )
        roster = models.Roster(
            name="Rozpiska",
            owner=user,
            army=army,
            ruleset_version="v1",
        )
        unit = models.RosterUnit(
            roster=roster,
            name="Samolot",
            models_per_unit=1,
            unit_copies=3,
            defense=3,
            toughness=1,
            passive_abilities_json='["guardian","airplane"]',
            special_abilities_json='[{"slug":"aura","target_slug":"guardian"}]',
            profiles_json=_profiles(),
            position=0,
            unit_cost=1,
        )
        session.add_all([template, unit])
        session.commit()

    assert upgrade_opos_database(test_engine) == 4

    with Session(test_engine) as session:
        template = session.query(models.UnitTemplate).one()
        unit = session.query(models.RosterUnit).one()
        roster = session.query(models.Roster).one()
        request = request_from_snapshot(
            unit,
            unit_copies=unit.unit_copies,
            custom_stats_enabled=roster.custom_stats_enabled,
            small_battle_enabled=roster.small_battle_enabled,
        )
        assert template.toughness == Decimal("2")
        assert unit.toughness == Decimal("2")
        assert request.passive_abilities == ("breakthrough", "airplane")
        assert request.special_abilities[0].target_slug == "breakthrough"
        assert unit.unit_cost > 1
        assert unit.unit_copies == 3
        assert roster.ruleset_version == "v3"
        assert template.ruleset_version == "v3"
        assert session.execute(text("PRAGMA user_version")).scalar_one() == (
            OPOS_V3_1_USER_VERSION
        )

    assert upgrade_opos_database(test_engine) == 0
    with Session(test_engine) as session:
        assert session.query(models.RosterUnit).one().toughness == Decimal("2")


def test_opos_1_2_migration_rolls_back_on_invalid_snapshot() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        user = models.User(username="owner", password_hash="hash")
        roster = models.Roster(name="Rozpiska", owner=user, ruleset_version="v1")
        session.add(
            models.RosterUnit(
                roster=roster,
                name="Błędny",
                models_per_unit=1,
                unit_copies=1,
                defense=3,
                toughness=1,
                passive_abilities_json='["nie-istnieje"]',
                special_abilities_json="[]",
                profiles_json=_profiles(),
                position=0,
                unit_cost=7,
            )
        )
        session.commit()

    with pytest.raises(QuoteValidationError, match="Unknown passive ability"):
        upgrade_opos_database(test_engine)

    with Session(test_engine) as session:
        unit = session.query(models.RosterUnit).one()
        assert unit.toughness == Decimal("1")
        assert unit.unit_cost == 7
        assert session.execute(text("PRAGMA user_version")).scalar_one() == 0


def test_v3_migration_rolls_back_on_out_of_range_custom_snapshot() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    profiles = json.loads(_profiles())
    profiles["melee"]["strength"] = 20
    with Session(test_engine) as session:
        user = models.User(username="owner-v3", password_hash="hash")
        roster = models.Roster(
            name="Błędna v3",
            owner=user,
            ruleset_version="v1",
            custom_stats_enabled=True,
        )
        session.add(
            models.RosterUnit(
                roster=roster,
                name="Poza zakresem",
                models_per_unit=1,
                unit_copies=1,
                defense=3,
                toughness=2,
                passive_abilities_json="[]",
                special_abilities_json="[]",
                profiles_json=json.dumps(profiles),
                position=0,
                unit_cost=7,
            )
        )
        session.execute(text("PRAGMA user_version = 10300"))
        session.commit()

    with pytest.raises(RuntimeError, match="nie jest zgodny z OPOS v3"):
        upgrade_opos_database(test_engine)

    with Session(test_engine) as session:
        roster = session.query(models.Roster).one()
        unit = session.query(models.RosterUnit).one()
        assert roster.ruleset_version == "v1"
        assert unit.unit_cost == 7
        assert session.execute(text("PRAGMA user_version")).scalar_one() == 10300
