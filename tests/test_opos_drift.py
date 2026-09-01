from pathlib import Path

from scripts.opos_rules_check import _semantic_document_errors, run_checks
from app.services.opos_rules import load_opos_ruleset


def test_published_documents_yaml_and_icons_have_no_semantic_drift() -> None:
    assert run_checks() == []


def test_semantic_check_reports_missing_critical_rules() -> None:
    errors = _semantic_document_errors(
        "Bohater", label="fixture", ruleset=load_opos_ruleset()
    )

    assert any("Samolot" in error for error in errors)
    assert any("Zabójczy ×4" in error for error in errors)
    assert any("Podwójny" in error for error in errors)
    assert any("Aura dla profili ataku" in error for error in errors)
    assert any("najdroższy profil" in error for error in errors)
    assert any("Samolot 0/0/1,6" in error for error in errors)


def test_ruleset_sources_point_to_published_opos_documents() -> None:
    ruleset = load_opos_ruleset()

    assert Path(ruleset.sources.normative).name == "OPOS.docx"
    assert Path(ruleset.sources.published).name == "OPOS.pdf"
