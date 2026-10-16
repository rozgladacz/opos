from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT_DIR / "app" / "templates"


def test_static_asset_urls_are_origin_relative() -> None:
    rendered_templates = {
        "base.html": (TEMPLATES_DIR / "base.html").read_text(encoding="utf-8"),
        "partials/icon.html": (TEMPLATES_DIR / "partials" / "icon.html").read_text(
            encoding="utf-8"
        ),
        "roster_edit.html": (TEMPLATES_DIR / "roster_edit.html").read_text(
            encoding="utf-8"
        ),
    }

    assert 'href="/static/favicon.svg"' in rendered_templates["base.html"]
    assert 'href="/static/css/style.css?' in rendered_templates["base.html"]
    assert 'src="/static/js/opos.js?' in rendered_templates["base.html"]
    assert 'href="/static/icons/opos.svg#icon-' in rendered_templates[
        "partials/icon.html"
    ]
    assert 'src="/static/js/opos_editor.js?' in rendered_templates[
        "roster_edit.html"
    ]
    assert all("url_for('static'" not in source for source in rendered_templates.values())
