import json
import os
import secrets
import stat
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_or_create_secret(env_name: str, file_name: str) -> str:
    """Return a secret resolving in this order: env var, persisted file, freshly generated.

    Generated secrets are written to ``DATA_DIR/file_name`` with 0600 permissions so
    that the application "just works" after a fresh install with no manual config.
    """

    env_value = os.getenv(env_name)
    if env_value:
        return env_value

    secret_path = DATA_DIR / file_name
    try:
        existing = secret_path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    except OSError:
        pass

    new_secret = secrets.token_urlsafe(48)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = secret_path.with_suffix(secret_path.suffix + ".tmp")
    tmp_path.write_text(new_secret, encoding="utf-8")
    try:
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    os.replace(tmp_path, secret_path)
    return new_secret


SECRET_KEY = _load_or_create_secret("SECRET_KEY", ".secret_key")
INITIAL_ADMIN_PASSWORD = _load_or_create_secret(
    "INITIAL_ADMIN_PASSWORD", ".initial_admin_password"
)
DB_URL = os.getenv("DB_URL", "sqlite:///./data/opos.db")
DEBUG = os.getenv("DEBUG", "false").lower() in {"1", "true", "yes"}
OPOS_RULESET_VERSION = os.getenv("OPOS_RULESET_VERSION", "v3")
UPDATE_REPO_URL = os.getenv("UPDATE_REPO_URL", "https://github.com/rozgladacz/opos")
UPDATE_BRANCH = os.getenv("UPDATE_BRANCH", "main")
UPDATE_REPO_PATH = os.getenv("UPDATE_REPO_PATH", ".")
UPDATE_REF = os.getenv("UPDATE_REF", "")
UPDATE_DOCKERFILE = os.getenv("UPDATE_DOCKERFILE", "Dockerfile")
UPDATE_COMPOSE_FILE = os.getenv("UPDATE_COMPOSE_FILE", "docker-compose.yml")
UPDATE_SERVICE_NAME = os.getenv("UPDATE_SERVICE_NAME", "opos-app")
UPDATE_IMAGE = os.getenv("UPDATE_IMAGE", "ghcr.io/rozgladacz/opos:latest")
UPDATE_WEBHOOK_TOKEN = _load_or_create_secret("UPDATE_WEBHOOK_TOKEN", ".webhook_token")
APP_VERSION = os.getenv("APP_VERSION", "dev")

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", str(DATA_DIR / "backups")))
BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "14"))
BACKUP_HOUR = int(os.getenv("BACKUP_HOUR", "3"))

TRUSTED_HOSTS = [
    host.strip()
    for host in os.getenv("TRUSTED_HOSTS", "*").split(",")
    if host.strip()
] or ["*"]

SESSION_HTTPS_ONLY = os.getenv("SESSION_HTTPS_ONLY", "false").lower() in {"1", "true", "yes"}


def _load_json_list(env_key: str, default: list) -> list:
    raw_value = os.getenv(env_key)
    if not raw_value:
        return default
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return default
    return parsed if isinstance(parsed, list) else default


COMMAND_RUNNER_ALLOWED_COMMANDS = _load_json_list("COMMAND_RUNNER_ALLOWED_COMMANDS", [])
COMMAND_RUNNER_SEQUENCE = _load_json_list("COMMAND_RUNNER_SEQUENCE", [])
COMMAND_RUNNER_WORKDIR = Path(os.getenv("COMMAND_RUNNER_WORKDIR", "."))
