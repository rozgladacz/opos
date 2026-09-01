"""Karty OPOS: ten sam dokument Jinja dla HTML i WeasyPrint PDF."""

from __future__ import annotations

import re
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models
from ..db import get_db
from ..paths import STATIC_DIR, TEMPLATES_DIR
from ..security import get_current_user
from ..services.cards import build_card_pages
from ..services.icon_sprite import render_card_icon


router = APIRouter(prefix="/rosters", tags=["cards"])
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["opos_icon_svg"] = render_card_icon
current_user_dep = get_current_user()
_STATIC_ROOT = STATIC_DIR.resolve()


def _browser_pdf_executable() -> Path | None:
    configured = os.getenv("OPOS_PDF_BROWSER")
    candidates = [Path(configured)] if configured else []
    if sys.platform == "win32":
        for root_name in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            root = os.getenv(root_name)
            if root:
                candidates.extend(
                    [
                        Path(root) / "Microsoft/Edge/Application/msedge.exe",
                        Path(root) / "Google/Chrome/Application/chrome.exe",
                    ]
                )
    return next((path for path in candidates if path.is_file()), None)


def _render_pdf_with_browser(html: str) -> bytes:
    browser = _browser_pdf_executable()
    if browser is None:
        raise RuntimeError("Nie znaleziono lokalnej przeglądarki do eksportu PDF")
    with tempfile.TemporaryDirectory(prefix="opos-pdf-") as temp_name:
        temp_dir = Path(temp_name)
        html_path = temp_dir / "cards.html"
        pdf_path = temp_dir / "cards.pdf"
        html_path.write_text(html, encoding="utf-8")
        command = [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--metrics-recording-only",
            "--no-first-run",
            "--no-pdf-header-footer",
            f"--user-data-dir={temp_dir / 'browser-profile'}",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=45,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not pdf_path.is_file():
            message = completed.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(message or "Przeglądarka nie utworzyła pliku PDF")
        pdf = pdf_path.read_bytes()
        if not pdf.startswith(b"%PDF-"):
            raise RuntimeError("Przeglądarka zwróciła niepoprawny plik PDF")
        return pdf


def _render_pdf(html: str) -> bytes:
    try:
        from weasyprint import HTML
    except (ImportError, OSError):
        return _render_pdf_with_browser(html)
    return HTML(
        string=html,
        base_url=_STATIC_ROOT.as_uri(),
        url_fetcher=_safe_asset_fetcher,
    ).write_pdf()


def _load_roster_and_units(
    db: Session, roster_id: int, user_id: int
) -> tuple[models.Roster, list[models.RosterUnit]]:
    roster = db.execute(
        select(models.Roster).where(
            models.Roster.id == roster_id,
            models.Roster.owner_id == user_id,
        )
    ).scalar_one_or_none()
    if roster is None:
        raise HTTPException(status_code=404, detail="Rozpiska nie istnieje")
    units = db.execute(
        select(models.RosterUnit)
        .where(models.RosterUnit.roster_id == roster.id)
        .order_by(models.RosterUnit.position, models.RosterUnit.id)
    ).scalars().all()
    return roster, units


def _safe_asset_fetcher(url: str) -> dict[str, object]:
    parsed = urlparse(url)
    if parsed.scheme != "file":
        raise ValueError("WeasyPrint may load local static assets only")
    raw_path = url2pathname(unquote(parsed.path))
    if re.match(r"^[/\\][A-Za-z]:", raw_path):
        raw_path = raw_path[1:]
    path = Path(raw_path).resolve()
    if not path.is_relative_to(_STATIC_ROOT):
        raise ValueError("WeasyPrint asset is outside app/static")
    from weasyprint import default_url_fetcher

    return default_url_fetcher(url)


def _card_context(
    request: Request,
    roster: models.Roster,
    units: list[models.RosterUnit],
    *,
    asset_base: str,
    is_pdf: bool,
) -> dict[str, object]:
    return {
        "request": request,
        "roster": roster,
        "pages": build_card_pages(
            units,
            ruleset_version=roster.ruleset_version,
            points_scale=roster.points_scale or 10,
            small_battle_enabled=roster.small_battle_enabled,
            shield_fist_enabled=roster.shield_fist_enabled,
        ),
        "asset_base": asset_base.rstrip("/"),
        "is_pdf": is_pdf,
    }


@router.get("/{roster_id}/cards", response_class=HTMLResponse)
def roster_cards(
    roster_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
):
    roster, units = _load_roster_and_units(db, roster_id, user.id)
    return templates.TemplateResponse(
        request,
        "cards.html",
        _card_context(
            request, roster, units, asset_base="/static", is_pdf=False
        ),
    )


@router.get("/{roster_id}/cards.pdf")
def roster_cards_pdf(
    roster_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user_dep),
) -> Response:
    roster, units = _load_roster_and_units(db, roster_id, user.id)
    if not units:
        raise HTTPException(status_code=409, detail="Rozpiska nie zawiera kart")
    html = templates.get_template("cards.html").render(
        _card_context(
            request,
            roster,
            units,
            asset_base=_STATIC_ROOT.as_uri(),
            is_pdf=True,
        )
    )
    try:
        pdf = _render_pdf(html)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        logger.exception("Nie udało się wygenerować kart PDF")
        raise HTTPException(
            status_code=503,
            detail="Eksport PDF jest chwilowo niedostępny.",
        ) from exc
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", roster.name).strip("-") or "rozpiska"
    headers = {"Content-Disposition": f'inline; filename="{safe_name}-karty.pdf"'}
    return Response(content=pdf, media_type="application/pdf", headers=headers)
