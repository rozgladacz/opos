import re
import secrets
from typing import Optional

import bcrypt
from fastapi import Depends, Header, HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import models
from .db import get_db

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto",
)

# Dozwolone znaki nazwy użytkownika: litery (w tym Unicode/polskie), cyfry,
# podkreślenie, spacja, kropka i myślnik. Whitelist celowo NIE dopuszcza
# cudzysłowów, nawiasów ostrokątnych, ampersanda ani innych znaków, które
# mogłyby wyłamać się z kontekstu HTML/JS przy renderowaniu nazwy.
USERNAME_MAX_LENGTH = 64
_USERNAME_RE = re.compile(r"^[\w][\w .\-]{0,%d}$" % (USERNAME_MAX_LENGTH - 1), re.UNICODE)
_CSRF_SESSION_KEY = "csrf_token"


def is_valid_username(username: str) -> bool:
    """Czy nazwa użytkownika zawiera wyłącznie bezpieczne znaki."""
    return bool(_USERNAME_RE.fullmatch(username))


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def _is_bcrypt_hash(hashed_password: str) -> bool:
    return hashed_password.startswith(("$2a$", "$2b$", "$2y$", "$2$"))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if _is_bcrypt_hash(hashed_password):
        # Legacy bcrypt hashes are limited to 72 bytes; truncate to avoid backend errors.
        return bcrypt.checkpw(
            plain_password.encode("utf-8")[:72],
            hashed_password.encode("utf-8"),
        )
    return pwd_context.verify(plain_password, hashed_password)


def get_csrf_token(request: Request) -> str:
    token = request.session.get(_CSRF_SESSION_KEY)
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        request.session[_CSRF_SESSION_KEY] = token
    return token


def validate_csrf(request: Request, submitted_token: str | None) -> None:
    expected = request.session.get(_CSRF_SESSION_KEY)
    if (
        not isinstance(expected, str)
        or not submitted_token
        or not secrets.compare_digest(expected, submitted_token)
    ):
        raise HTTPException(status_code=403, detail="Nieprawidłowy token CSRF")


def require_csrf(
    request: Request,
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    validate_csrf(request, x_csrf_token)


def get_current_user(optional: bool = False, *, close_session: bool = False):
    def dependency(
        request: Request, db: Session = Depends(get_db)
    ) -> Optional[models.User]:
        user_id = request.session.get("user_id")
        if not user_id:
            if optional:
                return None
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

        user = db.get(models.User, user_id)
        if user is None:
            request.session.pop("user_id", None)
            if optional:
                return None
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

        if close_session:
            db.expunge(user)
            db.close()

        return user

    return dependency
