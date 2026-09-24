from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services import update_service


def _configure_update_state(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(update_service, "DATA_DIR", data_dir)
    for attribute, filename in {
        "_STATUS_FILE": "update_status.json",
        "_LOG_FILE": "update_logs.jsonl",
        "_LAST_RUN_FILE": "update_last_run.json",
        "_STATE_FILE": "update_state.json",
        "_LAST_STATE_FILE": "update_last_state.json",
    }.items():
        monkeypatch.setattr(update_service, attribute, data_dir / filename)


def test_update_lock_is_written_to_data_dir_not_repository(monkeypatch, tmp_path) -> None:
    _configure_update_state(monkeypatch, tmp_path)
    repository = tmp_path / "read-only-application"
    monkeypatch.setattr(update_service, "UPDATE_REPO_PATH", str(repository))

    update_service.claim_update_slot("task-1")

    lock_path = tmp_path / "data" / ".update.lock"
    assert json.loads(lock_path.read_text(encoding="utf-8"))["task_id"] == "task-1"
    assert not repository.exists()
    update_service.release_update_slot()
    assert not lock_path.exists()


def test_lock_io_failure_is_reported_as_blocked(monkeypatch, tmp_path) -> None:
    _configure_update_state(monkeypatch, tmp_path)
    monkeypatch.setattr(update_service, "_lock_file_path", lambda: tmp_path)

    with pytest.raises(update_service.UpdateBlockedError, match="DATA_DIR"):
        update_service.claim_update_slot("task-2")


def test_last_run_failure_releases_acquired_lock(monkeypatch, tmp_path) -> None:
    _configure_update_state(monkeypatch, tmp_path)

    def fail_to_write_last_run(*args, **kwargs) -> None:
        del args, kwargs
        raise OSError("read-only")

    monkeypatch.setattr(update_service, "_write_last_run", fail_to_write_last_run)

    with pytest.raises(update_service.UpdateBlockedError, match="DATA_DIR"):
        update_service.claim_update_slot("task-3")

    assert not (tmp_path / "data" / ".update.lock").exists()


def test_lock_write_failure_removes_partial_lock(monkeypatch, tmp_path) -> None:
    _configure_update_state(monkeypatch, tmp_path)

    def fail_to_open_file(*args, **kwargs):
        del args, kwargs
        raise OSError("disk full")

    monkeypatch.setattr(update_service.os, "fdopen", fail_to_open_file)

    with pytest.raises(update_service.UpdateBlockedError, match="DATA_DIR"):
        update_service.claim_update_slot("task-4")

    assert not (tmp_path / "data" / ".update.lock").exists()


def test_detached_worker_uses_shared_data_and_host_compose_file(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "data"
    container_id_file = tmp_path / "hostname"
    container_id_file.write_text("abcdef123456\n", encoding="ascii")
    compose_file = "/srv/opos/docker-compose.yml"
    image_id = f"sha256:{'1' * 64}"
    captured: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(update_service, "DATA_DIR", data_dir)
    monkeypatch.setattr(update_service, "_CONTAINER_ID_FILE", container_id_file)
    monkeypatch.setattr(update_service, "UPDATE_COMPOSE_FILE", compose_file)
    monkeypatch.setattr(update_service, "UPDATE_SERVICE_NAME", "opos-app")

    def fake_run(command, **kwargs):
        captured.append((command, kwargs))
        stdout = f"{image_id}\n" if command[1] == "inspect" else f"{'2' * 64}\n"
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(update_service.subprocess, "run", fake_run)

    update_service._launch_update_service_worker("abcdef1234567890")

    assert captured[0][0] == [
        "/usr/local/bin/docker",
        "inspect",
        "--format={{.Image}}",
        "abcdef123456",
    ]
    command = captured[1][0]
    assert command[:3] == ["/usr/local/bin/docker", "run", "--detach"]
    volumes_from_index = command.index("--volumes-from")
    assert command[volumes_from_index : volumes_from_index + 2] == [
        "--volumes-from",
        "abcdef123456",
    ]
    assert "/srv/opos:/srv/opos:ro" in command
    assert f"DATA_DIR={data_dir.resolve()}" in command
    assert "UPDATE_REPO_PATH=/srv/opos" in command
    assert image_id in command
    assert command[-4:] == [
        "python",
        "-m",
        "app.scripts.update_once",
        "abcdef1234567890",
    ]
    for _, kwargs in captured:
        assert kwargs == {
            "capture_output": True,
            "text": True,
            "errors": "replace",
            "check": False,
            "timeout": 30,
        }


@pytest.mark.parametrize(
    ("container_id", "compose_file", "service_name", "expected_error"),
    [
        ("--privileged", "/srv/opos/docker-compose.yml", "opos-app", "identyfikator"),
        ("abcdef123456", "/docker-compose.yml", "opos-app", "bezpieczną ścieżkę"),
        (
            "abcdef123456",
            "/srv/opos/docker-compose.yml",
            "--project-directory",
            "nazwa usługi",
        ),
    ],
)
def test_detached_worker_rejects_unsafe_configuration(
    monkeypatch,
    tmp_path,
    container_id,
    compose_file,
    service_name,
    expected_error,
) -> None:
    container_id_file = tmp_path / "hostname"
    container_id_file.write_text(container_id, encoding="ascii")
    monkeypatch.setattr(update_service, "_CONTAINER_ID_FILE", container_id_file)
    monkeypatch.setattr(update_service, "UPDATE_COMPOSE_FILE", compose_file)
    monkeypatch.setattr(update_service, "UPDATE_SERVICE_NAME", service_name)

    with pytest.raises(update_service.UpdateServiceLaunchError, match=expected_error):
        update_service._launch_update_service_worker("abcdef1234567890")


def test_queue_service_releases_lock_when_worker_cannot_start(monkeypatch, tmp_path) -> None:
    _configure_update_state(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"

    def fail_to_launch(task_id: str) -> None:
        del task_id
        raise update_service.UpdateServiceLaunchError("docker unavailable")

    monkeypatch.setattr(update_service, "_launch_update_service_worker", fail_to_launch)

    status = update_service.queue_update_service()

    assert status.status == "error"
    assert status.error == "docker unavailable"
    assert not (data_dir / ".update.lock").exists()


def test_blocked_queue_persists_status_when_data_dir_is_writable(monkeypatch, tmp_path) -> None:
    _configure_update_state(monkeypatch, tmp_path)

    def block_update(task_id: str) -> None:
        del task_id
        raise update_service.UpdateInProgressError("Aktualizacja już trwa.")

    monkeypatch.setattr(update_service, "claim_update_slot", block_update)

    status = update_service.queue_update_service()

    assert status.status == "blocked"
    assert update_service.read_status()["status"] == "blocked"


def test_queue_releases_lock_when_status_cannot_be_saved(monkeypatch, tmp_path) -> None:
    _configure_update_state(monkeypatch, tmp_path)

    def fail_to_set_status(*args, **kwargs):
        del args, kwargs
        raise OSError("disk full")

    monkeypatch.setattr(update_service, "set_status", fail_to_set_status)

    status = update_service.queue_update_service()

    assert status.status == "error"
    assert status.error == "disk full"
    assert not (tmp_path / "data" / ".update.lock").exists()
