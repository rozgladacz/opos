import io
import json
from pathlib import Path

import pytest
from pypdf import PdfReader
from starlette.requests import Request

from app import models
from app.routers.export import (
    _STATIC_ROOT,
    _browser_pdf_executable,
    _card_context,
    _render_pdf_with_browser,
    _safe_asset_fetcher,
    templates,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/font.ttf",
        "http://127.0.0.1/private",
        Path(__file__).resolve().as_uri(),
    ],
)
def test_pdf_fetcher_rejects_network_and_files_outside_static(url: str) -> None:
    with pytest.raises(ValueError):
        _safe_asset_fetcher(url)


@pytest.mark.skipif(
    _browser_pdf_executable() is None,
    reason="Brak lokalnej przeglądarki obsługującej headless PDF",
)
def test_browser_fallback_generates_real_pdf() -> None:
    html = """<!doctype html><meta charset=\"utf-8\"><style>@page { size: A4 landscape }</style><h1>OPOS</h1>"""

    pdf = _render_pdf_with_browser(html)

    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1_000


@pytest.mark.skipif(
    _browser_pdf_executable() is None,
    reason="Brak lokalnej przeglądarki obsługującej headless PDF",
)
def test_browser_fallback_renders_opos_card_document() -> None:
    roster = models.Roster(
        name="Smoke 1.2",
        ruleset_version="v1",
        collapse_descriptions=False,
    )
    unit = models.RosterUnit(
        name="Samolot testowy",
        models_per_unit=1,
        unit_copies=1,
        defense=3,
        toughness=4,
        passive_abilities_json='["airplane"]',
        special_abilities_json="[]",
        profiles_json=json.dumps(
            {
                range_slug: {"dice": 1, "strength": 0, "abilities": []}
                for range_slug in ("melee", "short", "long")
            }
        ),
        position=0,
        unit_cost=5,
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "scheme": "http",
        }
    )
    html = templates.get_template("cards.html").render(
        _card_context(
            request,
            roster,
            [unit],
            asset_base=_STATIC_ROOT.as_uri(),
            is_pdf=True,
        )
    )

    pdf = _render_pdf_with_browser(html)

    assert len(PdfReader(io.BytesIO(pdf)).pages) == 1
