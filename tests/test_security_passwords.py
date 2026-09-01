import sys
from pathlib import Path

import bcrypt

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.security import hash_password, verify_password  # noqa: E402


def test_hash_and_verify_long_password():
    password = "a" * 100

    hashed = hash_password(password)

    assert verify_password(password, hashed)


def test_verify_legacy_bcrypt_hash_does_not_raise_on_long_password():
    password = "b" * 100
    legacy_hash = bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt())

    assert verify_password(password, legacy_hash.decode("utf-8"))
