from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks

from ..config import (
    APP_VERSION,
    DATA_DIR,
    UPDATE_COMPOSE_FILE,
    UPDATE_IMAGE,
    UPDATE_REPO_PATH,
    UPDATE_SERVICE_NAME,
)
from . import updater

logger = logging.getLogger(__name__)

_STATUS_FILE = DATA_DIR / "update_status.json"
_LOG_FILE = DATA_DIR / "update_logs.jsonl"
_LOCK_FILENAME = ".update.lock"
_LAST_RUN_FILE = DATA_DIR / "update_last_run.json"
_STATE_FILE = DATA_DIR / "update_state.json"
_LAST_STATE_FILE = DATA_DIR / "update_last_state.json"
_RATE_LIMIT = timedelta(minutes=5)
_LOCK_STALE_AFTER = timedelta(hours=1)
_MAX_STATE_LOG_ENTRIES = 50
_LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_LOG_KEEP_LINES = 1000


class UpdateBlockedError(RuntimeError):
    """Raised when an update cannot be started."""


class UpdateInProgressError(UpdateBlockedError):
    """Raised when an update is already running."""


class UpdateRateLimitError(UpdateBlockedError):
    """Raised when updates are triggered too frequently."""


class UpdateServiceError(RuntimeError):
    """Raised when the update service sequence fails."""

    def __init__(self, message: str, *, label: str, output: str, progress: int) -> None:
        super().__init__(message)
        self.label = label
        self.output = output
        self.progress = progress


@dataclass(frozen=True)
class UpdateStatus:
    task_id: str
    status: str
    detail: str | None = None
    error: str | None = None
    progress: int | None = None
    updated_at: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(timestamp: str | None) -> datetime | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_remaining(remaining: timedelta) -> str:
    total_seconds = max(0, int(remaining.total_seconds()))
    minutes, seconds = divmod(total_seconds, 60)
    if minutes and seconds:
        return f"{minutes} min {seconds} s"
    if minutes:
        return f"{minutes} min"
    return f"{seconds} s"


def _write_status(status: UpdateStatus) -> None:
    payload = asdict(status)
    payload["updated_at"] = _now_iso()
    temp_path = _STATUS_FILE.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(_STATUS_FILE)
    _append_log(status)
    _append_state(status)


def _rotate_log_if_needed() -> None:
    """Truncate log file to last _LOG_KEEP_LINES when it exceeds _LOG_MAX_BYTES."""
    try:
        if _LOG_FILE.stat().st_size <= _LOG_MAX_BYTES:
            return
        lines = _LOG_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
        trimmed = lines[-_LOG_KEEP_LINES:]
        tmp = _LOG_FILE.with_suffix(".tmp")
        tmp.write_text("".join(trimmed), encoding="utf-8")
        os.replace(tmp, _LOG_FILE)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Nie udało się wyrotować pliku logów aktualizacji.")


def _append_log(status: UpdateStatus) -> None:
    message = status.detail or status.error or status.status
    entry = {
        "timestamp": _now_iso(),
        "status": status.status,
        "message": message,
    }
    if status.error:
        entry["error"] = status.error
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_FILE.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _rotate_log_if_needed()


def _read_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Nie udało się odczytać stanu aktualizacji z %s", path)
        return None


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _append_state(status: UpdateStatus) -> None:
    now_iso = _now_iso()
    state = _read_state(_STATE_FILE) or {
        "start": None,
        "stop": None,
        "status": "idle",
        "log": [],
    }
    message = status.detail or status.error or status.status
    entry = {
        "timestamp": now_iso,
        "status": status.status,
        "message": message,
    }
    if status.error:
        entry["error"] = status.error
    log_entries = list(state.get("log") or [])
    log_entries.append(entry)
    state["log"] = log_entries[-_MAX_STATE_LOG_ENTRIES:]
    if status.status == "queued":
        state["start"] = None
        state["stop"] = None
    elif status.status == "started":
        state["start"] = now_iso
        state["stop"] = None
    elif status.status in {"success", "error", "blocked"}:
        if status.status == "blocked":
            state["start"] = None
        state["stop"] = now_iso
    state["status"] = status.status
    _write_state(_STATE_FILE, state)
    if status.status in {"success", "error", "blocked"}:
        _write_state(_LAST_STATE_FILE, state)


def _read_last_run() -> datetime | None:
    if not _LAST_RUN_FILE.exists():
        return None
    try:
        payload = json.loads(_LAST_RUN_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return _parse_iso(payload.get("started_at"))


def _write_last_run(started_at: datetime) -> None:
    _LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LAST_RUN_FILE.write_text(
        json.dumps({"started_at": started_at.isoformat()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _resolve_update_repo_path() -> Path:
    repo_path = Path(UPDATE_REPO_PATH)
    if repo_path.is_absolute():
        return repo_path
    project_root = Path(__file__).resolve().parents[2]
    return project_root / repo_path


def _lock_file_path() -> Path:
    return _resolve_update_repo_path() / _LOCK_FILENAME


def _read_lock() -> dict[str, Any] | None:
    lock_path = _lock_file_path()
    if not lock_path.exists():
        return None
    try:
        return json.loads(lock_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _clear_stale_lock() -> None:
    info = _read_lock()
    if not info:
        return
    started_at = _parse_iso(info.get("started_at"))
    if started_at and datetime.now(timezone.utc) - started_at > _LOCK_STALE_AFTER:
        try:
            _lock_file_path().unlink()
        except OSError:
            logger.warning("Nie udało się usunąć przeterminowanej blokady aktualizacji.")


def _acquire_lock(task_id: str) -> None:
    _clear_stale_lock()
    lock_path = _lock_file_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise UpdateInProgressError("Aktualizacja już trwa.") from exc
    payload = {"task_id": task_id, "started_at": _now_iso()}
    with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
        lock_file.write(json.dumps(payload, ensure_ascii=False, indent=2))


def _release_lock() -> None:
    try:
        _lock_file_path().unlink()
    except FileNotFoundError:
        return
    except OSError:
        logger.warning("Nie udało się usunąć blokady aktualizacji.")


def read_status() -> dict[str, Any] | None:
    if not _STATUS_FILE.exists():
        return None
    try:
        return json.loads(_STATUS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Nie udało się odczytać pliku statusu aktualizacji %s", _STATUS_FILE)
        return None


def read_logs(limit: int = 10) -> list[dict[str, Any]]:
    if not _LOG_FILE.exists():
        return []
    try:
        lines = _LOG_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.warning("Nie udało się odczytać logów aktualizacji %s", _LOG_FILE)
        return []
    if limit > 0:
        lines = lines[-limit:]
    logs: list[dict[str, Any]] = []
    for line in lines:
        try:
            logs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return logs


def read_current_state() -> dict[str, Any] | None:
    return _read_state(_STATE_FILE)


def read_last_state() -> dict[str, Any] | None:
    return _read_state(_LAST_STATE_FILE)


def claim_update_slot(task_id: str) -> None:
    last_run = _read_last_run()
    if last_run:
        elapsed = datetime.now(timezone.utc) - last_run
        if elapsed < _RATE_LIMIT:
            remaining = _RATE_LIMIT - elapsed
            raise UpdateRateLimitError(
                f"Zbyt częste uruchamianie aktualizacji. Spróbuj ponownie za {_format_remaining(remaining)}."
            )
    _acquire_lock(task_id)
    _write_last_run(datetime.now(timezone.utc))


def release_update_slot() -> None:
    _release_lock()


def set_status(
    task_id: str,
    status: str,
    detail: str | None = None,
    error: str | None = None,
    progress: int | None = None,
) -> UpdateStatus:
    payload = UpdateStatus(
        task_id=task_id,
        status=status,
        detail=detail,
        error=error,
        progress=progress,
    )
    _write_status(payload)
    return payload


def read_lock_status() -> dict[str, Any] | None:
    _clear_stale_lock()
    info = _read_lock()
    if not info:
        return None
    payload: dict[str, Any] = {
        "task_id": info.get("task_id"),
        "started_at": info.get("started_at"),
    }
    started_at = _parse_iso(info.get("started_at"))
    if started_at:
        payload["age_seconds"] = int((datetime.now(timezone.utc) - started_at).total_seconds())
    return payload


def is_update_locked() -> bool:
    return read_lock_status() is not None


def _format_command_output(stdout: str, stderr: str) -> str:
    parts: list[str] = []
    if stdout:
        parts.append(f"stdout:\n{stdout}")
    if stderr:
        parts.append(f"stderr:\n{stderr}")
    return "\n".join(parts).strip() or "Brak danych wyjściowych."


def _run_update_command(task_id: str, label: str, command: list[str], progress: int) -> None:
    workdir = _resolve_update_repo_path()
    result = subprocess.run(
        command,
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )
    output = _format_command_output(result.stdout.strip(), result.stderr.strip())
    detail = f"{label}\n{output}"
    if result.returncode != 0:
        raise UpdateServiceError(
            f"Polecenie zakończone niepowodzeniem ({' '.join(command)}).",
            label=label,
            output=output,
            progress=progress,
        )
    set_status(
        task_id=task_id,
        status="progress",
        detail=detail,
        progress=progress,
    )


def run_update_service_sequence(task_id: str, *, claim_slot: bool = True) -> None:
    if claim_slot:
        try:
            claim_update_slot(task_id)
        except UpdateBlockedError as exc:
            set_status(
                task_id=task_id,
                status="blocked",
                detail=str(exc),
                progress=0,
            )
            return

    try:
        if not UPDATE_SERVICE_NAME:
            set_status(
                task_id=task_id,
                status="error",
                detail="Brak skonfigurowanej nazwy usługi (UPDATE_SERVICE_NAME).",
                error="UPDATE_SERVICE_NAME nie został ustawiony.",
                progress=0,
            )
            return

        set_status(
            task_id=task_id,
            status="started",
            detail="Rozpoczęto aktualizację usługi.",
            progress=0,
        )

        # Pobierz najnowszy obraz z rejestru (GHCR) — nie wymaga gita ani build-toolchainu.
        _run_update_command(
            task_id,
            f"Wykonywanie: docker compose pull {UPDATE_SERVICE_NAME}",
            [
                "docker",
                "compose",
                "-f",
                UPDATE_COMPOSE_FILE,
                "pull",
                UPDATE_SERVICE_NAME,
            ],
            50,
        )
        _run_update_command(
            task_id,
            f"Wykonywanie: docker compose up -d {UPDATE_SERVICE_NAME}",
            [
                "docker",
                "compose",
                "-f",
                UPDATE_COMPOSE_FILE,
                "up",
                "-d",
                UPDATE_SERVICE_NAME,
            ],
            90,
        )

        set_status(
            task_id=task_id,
            status="success",
            detail=f"Usługa została zaktualizowana (poprzednia wersja: {APP_VERSION}).",
            progress=100,
        )
    except UpdateServiceError as exc:
        logger.error("Aktualizacja usługi nie powiodła się: %s", exc)
        set_status(
            task_id=task_id,
            status="error",
            detail=f"{exc.label}\n{exc.output}",
            error=exc.output,
            progress=exc.progress,
        )
    except Exception as exc:  # pragma: no cover - unexpected guard
        logger.exception("Nieoczekiwany błąd aktualizacji usługi")
        set_status(
            task_id=task_id,
            status="error",
            detail="Aktualizacja usługi nie powiodła się.",
            error=str(exc),
        )
    finally:
        release_update_slot()


def queue_update(background_tasks: BackgroundTasks, ref: str | None = None, tag: str | None = None) -> UpdateStatus:
    task_id = uuid4().hex
    try:
        claim_update_slot(task_id)
    except UpdateBlockedError as exc:
        return set_status(
            task_id=task_id,
            status="blocked",
            detail=str(exc),
            progress=0,
        )
    status = UpdateStatus(
        task_id=task_id,
        status="queued",
        detail="Zadanie oczekuje na uruchomienie.",
        progress=0,
    )
    _write_status(status)
    background_tasks.add_task(_run_update, task_id, ref, tag)
    return status


def _run_update(task_id: str, ref: str | None, tag: str | None) -> None:
    try:
        _write_status(
            UpdateStatus(
                task_id=task_id,
                status="started",
                detail="Rozpoczęto aktualizację repozytorium.",
                progress=0,
            )
        )
        origin_url = updater._validate_repository()
        target_ref, target_label = updater._resolve_target(ref, tag)
        logger.info("Aktualizacja repozytorium %s do %s", origin_url, target_label)

        _write_status(
            UpdateStatus(
                task_id=task_id,
                status="progress",
                detail="Pobieranie zmian z repozytorium.",
                progress=25,
            )
        )
        updater._run_git_command("fetch", "--all", "--tags", "--prune")

        _write_status(
            UpdateStatus(
                task_id=task_id,
                status="progress",
                detail=f"Resetowanie do {target_label}.",
                progress=75,
            )
        )
        updater._run_git_command("reset", "--hard", target_ref)

        _write_status(
            UpdateStatus(
                task_id=task_id,
                status="success",
                detail=f"Repozytorium zaktualizowane do {target_label}.",
                progress=100,
            )
        )
    except updater.UpdateError as exc:
        logger.error("Aktualizacja repozytorium nie powiodła się: %s", exc)
        _write_status(
            UpdateStatus(
                task_id=task_id,
                status="error",
                detail="Aktualizacja repozytorium nie powiodła się.",
                error=str(exc),
            )
        )
    except Exception as exc:  # pragma: no cover - guard for unexpected failures
        logger.exception("Nieoczekiwany błąd aktualizacji repozytorium")
        _write_status(
            UpdateStatus(
                task_id=task_id,
                status="error",
                detail="Aktualizacja repozytorium nie powiodła się.",
                error=str(exc),
            )
        )
    finally:
        release_update_slot()
