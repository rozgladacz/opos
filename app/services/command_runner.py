from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..config import (
    COMMAND_RUNNER_ALLOWED_COMMANDS,
    COMMAND_RUNNER_SEQUENCE,
    COMMAND_RUNNER_WORKDIR,
)

logger = logging.getLogger(__name__)


class CommandRunnerError(Exception):
    """Raised when command execution fails or is not allowed."""


@dataclass(slots=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass(slots=True)
class CommandRunStatus:
    results: list[CommandResult]

    @property
    def ok(self) -> bool:
        return all(result.returncode == 0 for result in self.results)


def _ensure_list(value: Any, *, field_name: str) -> list:
    if isinstance(value, list):
        return value
    raise CommandRunnerError(f"Nieprawidłowy format pola {field_name}.")


def _normalize_command(command: str) -> str:
    return command.strip()


def _resolve_workdir(raw_workdir: str | None, root: Path) -> Path:
    if not raw_workdir:
        return root
    workdir = Path(raw_workdir)
    if not workdir.is_absolute():
        workdir = root / workdir
    return workdir


def _validate_allowed_commands(allowed_commands: Iterable[str]) -> set[str]:
    allowed = {_normalize_command(cmd) for cmd in allowed_commands if str(cmd).strip()}
    if not allowed:
        raise CommandRunnerError("Lista dozwolonych poleceń jest pusta.")
    return allowed


def _parse_sequence(raw_sequence: Iterable[Any]) -> list[dict[str, Any]]:
    sequence: list[dict[str, Any]] = []
    for item in raw_sequence:
        if not isinstance(item, dict):
            raise CommandRunnerError("Konfiguracja sekwencji poleceń jest niepoprawna.")
        command = item.get("command")
        if not isinstance(command, str) or not command.strip():
            raise CommandRunnerError("Brak nazwy polecenia w sekwencji.")
        args = item.get("args", [])
        args_list = _ensure_list(args, field_name="args")
        sequence.append(
            {
                "command": command,
                "args": [str(arg) for arg in args_list],
                "workdir": item.get("workdir"),
            }
        )
    if not sequence:
        raise CommandRunnerError("Sekwencja poleceń jest pusta.")
    return sequence


def _log_output(prefix: str, content: str) -> None:
    for line in content.splitlines():
        logger.info("%s%s", prefix, line)


def run_configured_sequence() -> CommandRunStatus:
    allowed_commands = _validate_allowed_commands(COMMAND_RUNNER_ALLOWED_COMMANDS)
    sequence = _parse_sequence(COMMAND_RUNNER_SEQUENCE)
    root = COMMAND_RUNNER_WORKDIR

    results: list[CommandResult] = []

    for entry in sequence:
        command_name = _normalize_command(entry["command"])
        if command_name not in allowed_commands:
            raise CommandRunnerError(f"Polecenie '{command_name}' nie jest dozwolone.")

        args = entry.get("args", [])
        workdir = _resolve_workdir(entry.get("workdir"), root)

        logger.info("Uruchamiam polecenie: %s %s", command_name, " ".join(args))
        try:
            completed = subprocess.run(
                [command_name, *args],
                cwd=workdir,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:  # pragma: no cover - environment guard
            raise CommandRunnerError(
                f"Polecenie '{command_name}' nie jest dostępne w systemie."
            ) from exc

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        if stdout:
            _log_output("stdout: ", stdout)
        if stderr:
            _log_output("stderr: ", stderr)

        result = CommandResult(
            command=[command_name, *args],
            returncode=completed.returncode,
            stdout=stdout,
            stderr=stderr,
        )
        results.append(result)

        if completed.returncode != 0:
            raise CommandRunnerError(
                f"Polecenie '{command_name}' zakończyło się kodem {completed.returncode}.",
            )

    return CommandRunStatus(results=results)
