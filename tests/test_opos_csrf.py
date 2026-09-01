import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.routers import admin
from app.security import get_csrf_token, validate_csrf


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "session": {}})


def test_csrf_token_is_stable_inside_session() -> None:
    request = _request()
    first = get_csrf_token(request)
    second = get_csrf_token(request)

    assert first == second
    assert len(first) >= 32


def test_csrf_rejects_missing_and_wrong_token() -> None:
    request = _request()
    token = get_csrf_token(request)

    for submitted in (None, "wrong"):
        with pytest.raises(HTTPException) as exc_info:
            validate_csrf(request, submitted)
        assert exc_info.value.status_code == 403

    validate_csrf(request, token)


def test_update_webhook_token_is_accepted_only_in_header(monkeypatch) -> None:
    monkeypatch.setattr(admin.config, "UPDATE_WEBHOOK_TOKEN", "secret")
    query_request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/admin/update/webhook",
            "query_string": b"token=secret",
            "headers": [],
        }
    )
    with pytest.raises(HTTPException) as exc_info:
        admin._require_webhook_token(query_request)
    assert exc_info.value.status_code == 401

    header_request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/admin/update/webhook",
            "query_string": b"",
            "headers": [(b"x-webhook-token", b"secret")],
        }
    )
    admin._require_webhook_token(header_request)
