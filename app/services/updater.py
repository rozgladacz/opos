from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from ..config import UPDATE_BRANCH, UPDATE_REF, UPDATE_REPO_URL

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class UpdateError(Exception):
    """Raised when updating the repository fails."""


def _normalize_url(url: str) -> str:
    """Return a comparable representation of Git URLs (ssh/https)."""
    cleaned = url.strip().rstrip("/")
    if not cleaned:
        return ""

    def _strip_git_suffix(path: str) -> str:
        return path[:-4] if path.endswith(".git") else path

    if cleaned.startswith("git@"):
        # git@github.com:owner/repo(.git)
        try:
            _, host_and_path = cleaned.split("@", 1)
            host, path = host_and_path.split(":", 1)
        except ValueError:
            return cleaned.lower()
        return f"{host.lower()}/{_strip_git_suffix(path).lstrip('/').lower()}"

    parsed = urlsplit(cleaned)
    if parsed.scheme and parsed.hostname:
        return f"{parsed.hostname.lower()}/{_strip_git_suffix(parsed.path).lstrip('/').lower()}"

    return _strip_git_suffix(cleaned).lower()


def _run_git_command(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            check=True,
            text=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment guard
        raise UpdateError("Polecenie git jest niedostępne w systemie.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()
        stdout = exc.stdout.strip()
        error_message = stderr or stdout or "Polecenie git zakończyło się niepowodzeniem."
        raise UpdateError(error_message) from exc
    return result.stdout.strip()


def _determine_branch() -> str:
    branch = UPDATE_BRANCH or _run_git_command("rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch == "HEAD":
        raise UpdateError("Nie można ustalić docelowej gałęzi do aktualizacji.")
    return branch


def _validate_repository() -> str:
    if not UPDATE_REPO_URL:
        raise UpdateError("Brak skonfigurowanego adresu repozytorium (UPDATE_REPO_URL).")

    git_dir = _PROJECT_ROOT / ".git"
    if not git_dir.exists():
        raise UpdateError("Katalog projektu nie jest repozytorium Git.")

    origin_url = _run_git_command("remote", "get-url", "origin")
    if _normalize_url(origin_url) != _normalize_url(UPDATE_REPO_URL):
        raise UpdateError("Skonfigurowany adres repozytorium nie jest zgodny z origin.")

    return origin_url


def sync_repository() -> str:
    return sync_repository_target()


def _resolve_target(ref: str | None, tag: str | None) -> tuple[str, str]:
    if ref and tag:
        raise UpdateError("Wskaż tylko ref lub tag do aktualizacji.")
    if ref:
        return ref, ref
    if tag:
        return f"refs/tags/{tag}", f"tag {tag}"
    if UPDATE_REF:
        return UPDATE_REF, UPDATE_REF

    branch = _determine_branch()
    return f"origin/{branch}", f"origin/{branch}"


def sync_repository_target(ref: str | None = None, tag: str | None = None) -> str:
    origin_url = _validate_repository()
    target_ref, target_label = _resolve_target(ref, tag)

    logger.info(
        "Rozpoczynam aktualizację repozytorium %s do %s", origin_url, target_label
    )
    _run_git_command("fetch", "--all", "--tags", "--prune")
    _run_git_command("reset", "--hard", target_ref)
    logger.info("Repozytorium zostało zresetowane do %s", target_label)

    return f"Repozytorium zaktualizowane do {target_label}."
